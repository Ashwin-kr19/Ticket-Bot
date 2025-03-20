from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import uuid
import datetime
from modules.auth import register_user, authenticate_user
from modules.databases import create_tables
from modules.chat import ChatHistory
from modules.llm_service import initialize_retrieval_chain, ChatGoogleGenerativeAI
from modules.ticket_manager import generate_problem_summary, save_ticket_details, get_saved_summaries, create_zendesk_ticket
from modules.utils import load_api_keys, translate_text, LANGUAGES

app = Flask(__name__)
app.secret_key = "your-secret-key-here"  # Replace with a secure key

# Fallback classes for LLM and chain
class FallbackLLM:
    def invoke(self, prompt):
        class Response:
            def __init__(self, content):
                self.content = content
        return Response("I'm currently experiencing connection issues. Please try again later or contact support if this persists.")

class FallbackChain:
    def __call__(self, inputs):
        return {"answer": "I'm unable to access the knowledge base at the moment. Please try basic troubleshooting steps or contact technical support."}

# Global storage for chats (not in session)
if 'chats' not in app.config:
    app.config['chats'] = {}

def initialize_system():
    if 'current_chat' not in session:
        session['current_chat'] = None
    if 'qa_chain' not in app.config:
        app.config['qa_chain'] = None
    if 'llm' not in app.config:
        app.config['llm'] = None
    if 'current_problem_summary' not in session:
        session['current_problem_summary'] = {}
    if 'current_timestamp' not in session:
        session['current_timestamp'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if 'api_keys' not in app.config:
        app.config['api_keys'] = load_api_keys()
    if 'user_details' not in session:
        session['user_details'] = None

def evaluate_and_respond(query, retriever_answer, llm, chat_history):
    if chat_history.awaiting_satisfaction:
        response = query.lower()  # The query will be "yes" or "no" from the button
        if response == 'yes':
            chat_history.awaiting_satisfaction = False
            return "I'm glad I could help! If you have any more questions, feel free to start a new chat. Goodbye! 😊"
        elif response == 'no':
            chat_history.awaiting_satisfaction = False
            return "I'm sorry I couldn't fully resolve your issue. I'm opening a live chat with an agent to assist you further."
        return "Please respond with 'yes' if satisfied or 'no' if you'd like to connect with a live agent."

    system_prompt = """You are a helpful customer support AI assistant. Your responses should be:
    1. Direct and professional
    2. Focused on solving the user's issue
    3. Free of any meta-commentary or evaluation prefixes
    4. Clear and actionable"""
    user_prompt = f"""User query: {query}
    Context from knowledge base: {retriever_answer}
    Provide a direct response to help the user. Do not include any evaluation statements or prefixes."""
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    
    try:
        response = llm.invoke(full_prompt)
        final_response = response.content.replace("Response:", "").replace("Answer:", "").strip()
        if final_response.startswith("The knowledge base"):
            final_response = " ".join(final_response.split()[5:])
        if not final_response.startswith("I'm having trouble") and not final_response.startswith("Error"):
            chat_history.awaiting_satisfaction = True
            return f"{final_response}\n\nAre you satisfied with this resolution? Please respond with 'yes' or 'no'."
        return final_response
    except Exception as e:
        return f"I'm having trouble processing your request. Could you please try rephrasing or provide more details? Error: {str(e)}"

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    if not session.get('user_details'):
        return redirect(url_for('user_details'))
    return redirect(url_for('chat'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if authenticate_user(username, password):
            session['username'] = username
            initialize_system()
            return redirect(url_for('user_details'))
        return render_template('login.html', error="Invalid username or password")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if register_user(username, password):
            return redirect(url_for('login'))
        return render_template('register.html', error="Username already exists")
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    app.config['chats'] = {}  # Clear chats on logout
    return redirect(url_for('login'))

@app.route('/user_details', methods=['GET', 'POST'])
def user_details():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        full_name = request.form['full_name']
        email = request.form['email']
        contact_number = request.form['contact_number']
        issue_description = request.form['issue_description']
        
        session['user_details'] = {
            'full_name': full_name,
            'email': email,
            'contact_number': contact_number,
            'issue_description': issue_description
        }
        return redirect(url_for('chat'))
    
    return render_template('user_details.html')

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))
    if not session.get('user_details'):
        return redirect(url_for('user_details'))
    
    initialize_system()
    chats = app.config['chats']
    current_chat = session['current_chat']
    lang_code = request.args.get('lang', 'en')  # Default to English

    if not app.config['llm']:
        try:
            google_api_key = app.config['api_keys'].get("GOOGLE_API_KEY", "dummy-key-for-testing")
            app.config['llm'] = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                google_api_key=google_api_key,
                temperature=0.3,
                max_tokens=1524,
            )
            app.config['qa_chain'] = initialize_retrieval_chain()
        except Exception as e:
            print(f"Error initializing AI assistant: {str(e)}")
            app.config['llm'] = FallbackLLM()
            app.config['qa_chain'] = FallbackChain()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'new_chat':
            chat_id = str(uuid.uuid4())
            chats[chat_id] = ChatHistory(max_history=5)
            chats[chat_id].user_details = session['user_details']
            session['current_chat'] = chat_id
            return redirect(url_for('chat', lang=lang_code))
        
        elif action == 'switch_chat':
            chat_id = request.form.get('chat_id')
            if chat_id in chats:
                session['current_chat'] = chat_id
            return redirect(url_for('chat', lang=lang_code))
        
        elif action == 'send_message':
            query = request.form.get('message')
            if query and current_chat and current_chat in chats:
                current_chat_obj = chats[current_chat]
                translated_query = translate_text(query, "en")
                current_chat_obj.add_message("user", query)
                
                if current_chat_obj.awaiting_satisfaction:
                    response = evaluate_and_respond(translated_query, "", app.config['llm'], current_chat_obj)
                else:
                    try:
                        retriever_answer = app.config['qa_chain']({"question": translated_query, "chat_history": current_chat_obj.get_conversation_pairs()})["answer"]
                    except Exception as e:
                        retriever_answer = f"Error retrieving answer: {str(e)}"
                    response = evaluate_and_respond(translated_query, retriever_answer, app.config['llm'], current_chat_obj)
                
                translated_response = translate_text(response, lang_code)
                current_chat_obj.add_message("assistant", translated_response)
                if "Goodbye" in response:
                    session['current_chat'] = None
                return redirect(url_for('chat', lang=lang_code))
        
        elif action == 'satisfaction_response':
            response = request.form.get('satisfaction_response')
            if current_chat and current_chat in chats:
                current_chat_obj = chats[current_chat]
                if current_chat_obj.awaiting_satisfaction:
                    translated_response = evaluate_and_respond(response, "", app.config['llm'], current_chat_obj)
                    current_chat_obj.add_message("user", response)
                    current_chat_obj.add_message("assistant", translated_response)
                    if "Goodbye" in translated_response:
                        session['current_chat'] = None
            return redirect(url_for('chat', lang=lang_code))
        
        elif action == 'generate_summary' and current_chat and current_chat in chats:
            current_chat_obj = chats[current_chat]
            if len(current_chat_obj.get_messages()) > 3:
                problem_summary = generate_problem_summary(current_chat_obj.get_messages(), app.config['llm'])
                if "Insufficient conversation history" not in problem_summary:
                    success = save_ticket_details(
                        current_chat,
                        session['username'],
                        current_chat_obj.user_details.get('full_name', 'Unknown'),
                        current_chat_obj.user_details.get('email', 'unknown@example.com'),
                        problem_summary
                    )
                    if success:
                        session['current_problem_summary'][current_chat] = problem_summary
            return redirect(url_for('chat', lang=lang_code))
        
        elif action == 'create_zendesk' and current_chat in session['current_problem_summary'] and current_chat in chats:
            current_chat_obj = chats[current_chat]
            problem_summary = session['current_problem_summary'][current_chat]
            user_name = current_chat_obj.user_details.get('full_name', 'Anonymous User')
            user_email = current_chat_obj.user_details.get('email', 'anonymous@example.com')
            success, message, ticket_url = create_zendesk_ticket(problem_summary, user_name, user_email)
            return redirect(url_for('chat', lang=lang_code))

    if current_chat and current_chat not in chats:
        session['current_chat'] = None
    if not current_chat and chats:
        session['current_chat'] = next(iter(chats))
    elif not current_chat:
        chat_id = str(uuid.uuid4())
        chats[chat_id] = ChatHistory(max_history=5)
        chats[chat_id].user_details = session['user_details']
        session['current_chat'] = chat_id

    current_chat_obj = chats.get(session['current_chat']) if session['current_chat'] else None
    return render_template('chat.html', username=session['username'], chats=chats, current_chat=current_chat, 
                           chat_history=current_chat_obj.get_messages() if current_chat_obj else [], 
                           problem_summary=session['current_problem_summary'].get(current_chat, None),
                           lang_code=lang_code, languages=LANGUAGES)

@app.route('/summaries')
def summaries():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    summaries = get_saved_summaries(session['username'])
    return render_template('summaries.html', summaries=summaries, username=session['username'])

@app.route('/create_zendesk_from_summary/<chat_id>')
def create_zendesk_from_summary(chat_id):
    if 'username' not in session:
        return redirect(url_for('login'))
    
    summaries = get_saved_summaries(session['username'])
    for summary in summaries:
        if summary[0] == chat_id:
            success, message, ticket_url = create_zendesk_ticket(summary[3], summary[1], summary[2])
            return redirect(url_for('summaries'))
    return redirect(url_for('summaries'))

if __name__ == "__main__":
    create_tables()
    app.run(debug=True, host='0.0.0.0', port=5002)