from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import uuid
import datetime
import logging
from modules.auth import register_user, authenticate_user
from modules.databases import create_tables
from modules.chat import ChatHistory
from modules.llm_service import initialize_retrieval_chain, ChatGoogleGenerativeAI
from modules.ticket_manager import generate_problem_summary, save_ticket_details, get_saved_summaries, create_zendesk_ticket
from modules.utils import load_api_keys, translate_text, LANGUAGES

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = "your-secret-key-here"

if 'chats' not in app.config:
    app.config['chats'] = {}

class FallbackLLM:
    def invoke(self, prompt):
        class Response:
            def __init__(self, content):
                self.content = content
        return Response("I'm currently experiencing connection issues. Please try again later or contact support.")

class FallbackChain:
    def __call__(self, inputs):
        return {"answer": "I'm unable to access the knowledge base right now. Please try basic troubleshooting or contact support."}

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
        session['current_timestamp'] = datetime.datetime.now().strftime("%Y-%m-%d")
    if 'api_keys' not in app.config:
        app.config['api_keys'] = load_api_keys()
    if 'user_details' not in session:
        session['user_details'] = None

def evaluate_and_respond(query, retriever_answer, llm, chat_history):
    if chat_history.awaiting_satisfaction and query.lower() in ['yes', 'no']:
        chat_history.awaiting_satisfaction = False
        if query.lower() == 'yes':
            return "I'm glad I could help! If you have more questions, start a new chat. Goodbye! 😊"
        elif query.lower() == 'no':
            return "I'm sorry I couldn’t resolve your issue. Connecting you to a live agent..."
        return "Please respond with 'yes' if satisfied or 'no' for a live agent."
    
    system_prompt = """You are a helpful customer support AI assistant. Your responses should be:
    1. Direct and professional
    2. Focused on solving the user's issue
    3. Free of meta-commentary
    4. Clear and actionable"""
    user_prompt = f"""User query: {query}
    Context from knowledge base: {retriever_answer}
    Provide a direct response to help the user."""
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    
    try:
        response = llm.invoke(full_prompt)
        final_response = response.content.replace("Response:", "").replace("Answer:", "").strip()
        if not final_response.startswith("I'm having trouble") and not final_response.startswith("Error"):
            chat_history.awaiting_satisfaction = True
            return f"{final_response}\n\nAre you satisfied with this resolution? Please respond with 'yes' or 'no'."
        return final_response
    except Exception as e:
        return f"I'm having trouble processing your request. Please rephrase or provide more details. Error: {str(e)}"

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('chat'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if authenticate_user(username, password):
            session['username'] = username
            initialize_system()
            return redirect(url_for('chat'))
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
    app.config['chats'] = {}
    return redirect(url_for('login'))

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    initialize_system()
    chats = app.config['chats']
    current_chat = session['current_chat']
    lang_code = request.args.get('lang', 'en')

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
            logger.error(f"Error initializing AI assistant: {str(e)}")
            app.config['llm'] = FallbackLLM()
            app.config['qa_chain'] = FallbackChain()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'new_chat':
            chat_id = str(uuid.uuid4())
            chats[chat_id] = ChatHistory(max_history=5)
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
                
                if current_chat_obj.state == "pre_chat":
                    if not current_chat_obj.name:
                        response = "What’s your full name?"
                    elif not current_chat_obj.email:
                        response = "What’s your email address?"
                    elif not current_chat_obj.phone_number:
                        response = "What’s your contact number?"
                    elif not current_chat_obj.issue_description:
                        response = "Please provide a small description of your issue or request."
                    translated_response = translate_text(response, lang_code)
                    current_chat_obj.add_message("assistant", translated_response)
                
                elif current_chat_obj.state == "identify_issue":
                    response = "What is the issue you are facing?"
                    translated_response = translate_text(response, lang_code)
                    current_chat_obj.add_message("assistant", translated_response)
                
                elif current_chat_obj.state == "customer_product":
                    if not current_chat_obj.customer:
                        response = "Which customer are you with? (Wheeltek, Celestina, New Nemar, Mazda, Motorace, First Valley Bank)"
                    elif not current_chat_obj.product:
                        response = "Which product is this about? (LOS, AIDC, UP, DENALI, IMD, ALPS, Autotech – MSC)"
                    translated_response = translate_text(response, lang_code)
                    current_chat_obj.add_message("assistant", translated_response)
                
                elif current_chat_obj.state == "specific_issue":
                    response = _get_specific_issue_prompt(current_chat_obj)
                    translated_response = translate_text(response, lang_code)
                    current_chat_obj.add_message("assistant", translated_response)
                
                elif current_chat_obj.state == "request_handling":
                    response = _get_request_prompt(current_chat_obj)
                    translated_response = translate_text(response, lang_code)
                    current_chat_obj.add_message("assistant", translated_response)
                
                elif current_chat_obj.state == "complete":
                    retriever_answer = app.config['qa_chain']({"question": translated_query, "chat_history": current_chat_obj.get_conversation_pairs()})["answer"]
                    response = evaluate_and_respond(translated_query, retriever_answer, app.config['llm'], current_chat_obj)
                    translated_response = translate_text(response, lang_code)
                    current_chat_obj.add_message("assistant", translated_response)
                
                return redirect(url_for('chat', lang=lang_code))
        
        elif action == 'satisfaction_response':
            response = request.form.get('satisfaction_response')
            if current_chat and current_chat in chats:
                current_chat_obj = chats[current_chat]
                translated_response = evaluate_and_respond(response, "", app.config['llm'], current_chat_obj)
                current_chat_obj.add_message("user", response)
                current_chat_obj.add_message("assistant", translated_response)
                if "Goodbye" in translated_response:
                    chat_id = str(uuid.uuid4())
                    chats[chat_id] = ChatHistory(max_history=5)
                    session['current_chat'] = chat_id
            return redirect(url_for('chat', lang=lang_code))
        
        elif action == 'generate_summary' and current_chat and current_chat in chats:
            current_chat_obj = chats[current_chat]
            if len(current_chat_obj.get_messages()) > 3:
                problem_summary = generate_problem_summary(current_chat_obj.get_messages(), app.config['llm'])
                if "Insufficient conversation history" not in problem_summary:
                    success = save_ticket_details(
                        current_chat,
                        session['username'],
                        current_chat_obj.name or 'Unknown',
                        current_chat_obj.email or 'unknown@example.com',
                        problem_summary
                    )
                    if success:
                        session['current_problem_summary'][current_chat] = problem_summary
            return redirect(url_for('chat', lang=lang_code))
        
        elif action == 'create_zendesk' and current_chat in session['current_problem_summary'] and current_chat in chats:
            current_chat_obj = chats[current_chat]
            problem_summary = session['current_problem_summary'][current_chat]
            user_name = current_chat_obj.name or 'Anonymous User'
            user_email = current_chat_obj.email or 'anonymous@example.com'
            chat_data = {
                'Email_id': current_chat_obj.email or '',
                'Product': current_chat_obj.product or '',
                'Customer': current_chat_obj.customer or '',
                'Created_Date': datetime.datetime.now().strftime("%Y-%m-%d"),
                'Incident_Type': 'Incident' if 'issue' in (current_chat_obj.issue_description or '').lower() else 'Request',
                'Ticket_Category': 'Technical',
                'Ticket_Type': 'Support',
                'Application': current_chat_obj.specific_data.get('application_id', '') or '',
                'Incident_Description': current_chat_obj.issue_description or '',
                'Name': current_chat_obj.name or '',
                'Phone_Number': current_chat_obj.phone_number or ''
            }
            logger.debug(f"Chat data for Zendesk: {chat_data}")
            success, message, ticket_url = create_zendesk_ticket(problem_summary, user_name, user_email, chat_data)
            logger.info(f"Zendesk ticket creation: Success={success}, Message={message}, URL={ticket_url}")
            return redirect(url_for('chat', lang=lang_code))
        
        elif action == 'delete_chat':
            chat_id = request.form.get('chat_id')
            if chat_id in chats:
                if chat_id == session['current_chat']:
                    session['current_chat'] = None
                del chats[chat_id]
                if not chats and 'current_chat' in session:
                    session['current_chat'] = None
                return redirect(url_for('chat', lang=lang_code))

    if current_chat and current_chat not in chats:
        session['current_chat'] = None
    if not current_chat:
        if chats:
            session['current_chat'] = next(iter(chats))
        else:
            chat_id = str(uuid.uuid4())
            chats[chat_id] = ChatHistory(max_history=5)
            session['current_chat'] = chat_id
    current_chat = session['current_chat']

    current_chat_obj = chats.get(current_chat)
    session_data = {
        'Email_id': current_chat_obj.email or '',
        'Product': current_chat_obj.product or '',
        'Customer': current_chat_obj.customer or '',
        'Created_Date': session.get('current_timestamp', ''),
        'Incident_Type': 'Incident' if 'issue' in (current_chat_obj.issue_description or '').lower() else 'Request',
        'Ticket_Category': 'Technical',
        'Ticket_Type': 'Support',
        'Application': current_chat_obj.specific_data.get('application_id', '') or '',
        'Incident_Description': current_chat_obj.issue_description or '',
        'Name': current_chat_obj.name or '',
        'Phone_Number': current_chat_obj.phone_number or ''
    } if current_chat_obj else {}
    
    return render_template('chat.html', username=session['username'], chats=chats, current_chat=current_chat, 
                           chat_history=current_chat_obj.get_messages() if current_chat_obj else [], 
                           problem_summary=session['current_problem_summary'].get(current_chat, None),
                           lang_code=lang_code, languages=LANGUAGES, session_data=session_data)

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

@app.route('/get_chat_data')
def get_chat_data():
    chat_id = request.args.get('chat_id')
    if chat_id in app.config['chats']:
        chat_obj = app.config['chats'][chat_id]
        return jsonify({
            'name': chat_obj.name,
            'email': chat_obj.email,
            'phone_number': chat_obj.phone_number,
            'issue_description': chat_obj.issue_description,
            'customer': chat_obj.customer,
            'product': chat_obj.product,
            'specific_data': chat_obj.specific_data
        })
    return jsonify({}), 404

def _get_specific_issue_prompt(chat_obj):
    issue_lower = chat_obj.issue_description.lower()
    if chat_obj.product == "los" and "application_id" not in chat_obj.specific_data:
        return "Please provide the Application ID."
    elif "login issue" in issue_lower and "screenshot" not in chat_obj.specific_data:
        return "Please provide a screenshot of the login issue."
    elif "auto logout" in issue_lower:
        if "screen_recording" not in chat_obj.specific_data:
            return "Can you provide a screen recording? (Yes/No)"
        elif "module" not in chat_obj.specific_data:
            return "Which module were you accessing?"
    elif "payment issue" in issue_lower and "receipt_number" not in chat_obj.specific_data:
        return "Please provide the Receipt Number or OR Number."
    elif "tpin issue" in issue_lower and "tpin_number" not in chat_obj.specific_data:
        return "Please provide the TPIN Number."
    elif "allocation" in issue_lower:
        if "screenshot" not in chat_obj.specific_data:
            return "Please provide a screenshot."
        elif "collection_specialist" not in chat_obj.specific_data:
            return "Please provide the Collection Specialist’s Full Name."
        elif "username" not in chat_obj.specific_data["collection_specialist"]:
            return "Please provide the Collection Specialist’s Username."
        elif "contact_number" not in chat_obj.specific_data["collection_specialist"]:
            return "Please provide the Collection Specialist’s Contact Number."
    elif chat_obj.product == "denali" and "login issue" in issue_lower:
        if "ebt_name" not in chat_obj.specific_data:
            return "Please provide the EBT Name."
        elif "branch_role" not in chat_obj.specific_data:
            return "Please provide the Branch Role."
        elif "screenshot" not in chat_obj.specific_data:
            return "Please provide a screenshot."
    return "I’ve collected all the details. How else can I assist you?"

def _get_request_prompt(chat_obj):
    request_lower = chat_obj.issue_description.lower()
    if "new user" in request_lower:
        if "employee_id" not in chat_obj.specific_data:
            return "Please provide the Employee ID or EBT Name."
        elif "full_name" not in chat_obj.specific_data:
            return "Please provide the Full Name."
        elif "contact_number" not in chat_obj.specific_data:
            return "Please provide the Contact Number."
        elif "email_id" not in chat_obj.specific_data:
            return "Please provide the Email ID."
        elif "role" not in chat_obj.specific_data:
            return "Please provide the Role."
        elif "branch" not in chat_obj.specific_data:
            return "Please provide the Branch."
    elif "contact number change" in request_lower and "new_number" not in chat_obj.specific_data:
        return "Please share the new number you want to update."
    elif "password reset" in request_lower:
        if "tried_forgot_password" not in chat_obj.specific_data:
            return "Have you tried the Forgot Password option on the login page? (Yes/No)"
        elif "screenshot" not in chat_obj.specific_data and "no" in chat_obj.specific_data["tried_forgot_password"].lower():
            return "Please provide a screenshot of the error."
    elif "module" in request_lower:
        if "branch" not in chat_obj.specific_data:
            return "Please provide the Branch."
        elif "role" not in chat_obj.specific_data:
            return "Please provide the Role."
    return "I’ve collected all the details. How else can I assist you?"

if __name__ == "__main__":
    create_tables()
    app.run(debug=True, host='0.0.0.0', port=5001)