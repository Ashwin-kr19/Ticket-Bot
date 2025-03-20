import datetime
import sqlite3
import streamlit as st
from modules.databases import DB_PATH, SUMMARIES_DIR
from modules.zen_desk import create_zendesk_ticket

def generate_problem_summary(chat_history, llm):
    """Generate a technical problem summary from chat history including user details"""
    # Extract user details and relevant messages
    user_details = {"full_name": None, "email": None}
    relevant_messages = []
    user_details_complete = False
    
    for msg in chat_history:
        # Extract full name from first user message
        if msg["role"] == "user" and not user_details["full_name"]:
            user_details["full_name"] = msg["content"]
            continue
            
        # Extract email from second user message
        if msg["role"] == "user" and not user_details["email"] and "@" in msg["content"]:
            user_details["email"] = msg["content"]
            continue
            
        # Skip initial user detail collection messages
        if not user_details_complete:
            if msg["content"].startswith("Thank you for providing your details"):
                user_details_complete = True
            continue
        
        # Add relevant messages to our conversation history
        if msg["role"] in ["user", "assistant"]:
            relevant_messages.append(f"{msg['role'].capitalize()}: {msg['content']}")
    
    # If we don't have enough relevant messages, return early
    if len(relevant_messages) < 2:
        return "Insufficient conversation history to generate summary."
    
    # Create a detailed prompt for the LLM
    prompt = """Based on the following support conversation and user details, create a comprehensive technical problem summary.

User Details:
Full Name: {full_name}
Email: {email}

Conversation:
{chat_text}

Generate a summary that includes:
1. User Information
2. The core issue reported
3. Key details provided by the user
4. Current troubleshooting status
5. Any solutions attempted

Format the summary in a clear, technical style. Include all user details and focus on the relevant technical information."""
    
    # Join the relevant messages with newlines
    chat_text = "\n".join(relevant_messages)
    
    try:
        # Generate the summary using the LLM
        response = llm.invoke(
            prompt.format(
                full_name=user_details["full_name"],
                email=user_details["email"],
                chat_text=chat_text
            )
        )
        return response.content.strip()
    except Exception as e:
        return f"Error generating summary: {str(e)}"

def save_ticket_details(chat_id, username, full_name, email, problem_summary):
    """Save ticket details to the database and to a file, and optionally to Zendesk"""
    # Save to database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    db_success = False
    try:
        cursor.execute("""
            INSERT INTO ticket_details (chat_id, username, full_name, email, problem_summary)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, username, full_name, email, problem_summary))
        conn.commit()
        db_success = True
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        conn.close()
    
    # Save to file
    file_success = False
    filename = ""
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{SUMMARIES_DIR}/{username}_{timestamp}_{chat_id[:8]}.txt"
        
        with open(filename, "w") as file:
            file.write(f"Ticket ID: {chat_id}\n")
            file.write(f"Username: {username}\n")
            file.write(f"Full Name: {full_name}\n")
            file.write(f"Email: {email}\n")
            file.write(f"Creation Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            file.write("\n------ PROBLEM SUMMARY ------\n\n")
            file.write(problem_summary)
        file_success = True
    except Exception as e:
        print(f"File write error: {e}")
    
    # Offer to create Zendesk ticket if file was saved successfully
    if db_success and file_success:
        if st.button("🎫 Create Zendesk Ticket Now"):
            formatted_summary = f"Ticket ID: {chat_id}\nUsername: {username}\nFull Name: {full_name}\nEmail: {email}\nCreation Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n------ PROBLEM SUMMARY ------\n\n{problem_summary}"
            success, message = create_zendesk_ticket(formatted_summary, full_name, email)
            if success:
                st.success(message)
            else:
                st.error(message)
    
    return db_success and file_success

def get_saved_summaries(username):
    """Fetch all summaries for a specific user from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT chat_id, full_name, email, problem_summary, created_at 
            FROM ticket_details 
            WHERE username = ?
            ORDER BY created_at DESC
        """, (username,))
        results = cursor.fetchall()
        return results
    except sqlite3.Error as e:
        print(f"Error fetching summaries: {e}")
        return []
    finally:
        conn.close()

def generate_and_save_ticket(chat_history, chat_id, username, llm):
    """Generate a problem summary and save it as a ticket, with option to create Zendesk ticket"""
    # Generate the problem summary
    problem_summary = generate_problem_summary(chat_history, llm)
    
    if problem_summary == "Insufficient conversation history to generate summary.":
        return False, problem_summary
    
    # Extract user details from chat history
    full_name = None
    email = None
    
    for msg in chat_history:
        if msg["role"] == "user" and not full_name:
            full_name = msg["content"]
            continue
        if msg["role"] == "user" and not email and "@" in msg["content"]:
            email = msg["content"]
            break
    
    # Save the ticket details
    success = save_ticket_details(chat_id, username, full_name, email, problem_summary)
    
    if success:
        return True, problem_summary
    else:
        return False, "Error saving ticket details."

def create_zendesk_from_summary(chat_id, username, full_name, email, problem_summary):
    """Create a Zendesk ticket from an existing problem summary"""
    formatted_summary = f"Ticket ID: {chat_id}\nUsername: {username}\nFull Name: {full_name}\nEmail: {email}\nCreation Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n------ PROBLEM SUMMARY ------\n\n{problem_summary}"
    return create_zendesk_ticket(formatted_summary, full_name, email)
