import os
import sqlite3
import json
import requests
import streamlit as st

ZENDESK_SUBDOMAIN = "tvs8274"
ZENDESK_EMAIL = "20pd06@psgtech.ac.in"
ZENDESK_API_TOKEN = "yw1K4JFOJnMkYLTBW3gO13CMBVKMBfryk0vO93uc"

def generate_problem_summary(chat_history, llm):
    user_details = {"full_name": None, "email": None}
    relevant_messages = []
    user_details_complete = False
    
    for msg in chat_history:
        if msg["role"] == "user" and not user_details["full_name"]:
            user_details["full_name"] = msg["content"]
            continue
        if msg["role"] == "user" and not user_details["email"] and "@" in msg["content"]:
            user_details["email"] = msg["content"]
            continue
        if not user_details_complete:
            if msg["content"].startswith("Thank you for providing your details"):
                user_details_complete = True
            continue
        if msg["role"] in ["user", "assistant"]:
            relevant_messages.append(f"{msg['role'].capitalize()}: {msg['content']}")
    
    if len(relevant_messages) < 2:
        return "Insufficient conversation history to generate summary."
    
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
Format the summary in a clear, technical style."""
    
    chat_text = "\n".join(relevant_messages)
    try:
        response = llm.invoke(prompt.format(full_name=user_details["full_name"], email=user_details["email"], chat_text=chat_text))
        return response.content.strip()
    except Exception as e:
        return f"Error generating summary: {str(e)}"

def save_ticket_details(ticket_id, username, full_name, email, problem_summary):
    try:
        os.makedirs("summaries", exist_ok=True)
        with open(f"summaries/{ticket_id}.txt", "w") as f:
            f.write(f"Ticket ID: {ticket_id}\n")
            f.write(f"Agent: {username}\n")
            f.write(f"Customer Name: {full_name}\n")
            f.write(f"Customer Email: {email}\n")
            f.write(f"Date: {st.session_state.get('current_timestamp', 'N/A')}\n\n")
            f.write(f"Problem Summary:\n{problem_summary}")
        
        conn = sqlite3.connect('ticketbot.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS ticket_summaries (
            ticket_id TEXT PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            email TEXT,
            problem_summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute("INSERT INTO ticket_summaries (ticket_id, username, full_name, email, problem_summary) VALUES (?, ?, ?, ?, ?)",
                  (ticket_id, username, full_name, email, problem_summary))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving ticket details: {e}")
        return False

def get_saved_summaries(username):
    try:
        conn = sqlite3.connect('ticketbot.db')
        c = conn.cursor()
        c.execute("SELECT ticket_id, full_name, email, problem_summary, created_at FROM ticket_summaries WHERE username = ? ORDER BY created_at DESC", (username,))
        summaries = c.fetchall()
        conn.close()
        return summaries
    except Exception as e:
        print(f"Error retrieving summaries: {e}")
        return []

def create_zendesk_ticket(problem_summary, user_name=None, user_email=None, chat_data=None):
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets.json"
    chat_data = chat_data or {}
    specific_data_str = "\n".join([f"{k}: {v}" for k, v in chat_data.get('specific_data', {}).items()])
    ticket = {
        "subject": f"Support Request: {user_name if user_name else 'New User'}",
        "comment": {"body": f"{problem_summary}\n\nAdditional Details:\n{specific_data_str}"},
        "priority": "normal",
        "custom_fields": [
            {"id": "25372912209938", "value": chat_data.get('issue_description', 'Other')},  # Issue Description
            {"id": "25379100976786", "value": chat_data.get('product', 'Not provided')},     # Product
            {"id": "25391550675474", "value": chat_data.get('customer', 'Not provided')},    # Customer
            {"id": "25391564681106", "value": chat_data.get('name', 'Not provided')},        # Name
            {"id": "25391578097426", "value": chat_data.get('phone_number', None)}           # Phone Number
        ]
    }
    if user_email:
        ticket["requester"] = {"email": user_email, "name": user_name if user_name else "Requester"}
    ticket_data = {"ticket": ticket}
    headers = {"Content-Type": "application/json"}
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
    
    try:
        response = requests.post(url, auth=auth, headers=headers, data=json.dumps(ticket_data), timeout=10)
        if response.status_code == 201:
            ticket_id = response.json()['ticket']['id']
            ticket_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/agent/tickets/{ticket_id}"
            return True, f"Ticket #{ticket_id} created successfully.", ticket_url
        return False, f"Failed to create ticket: {response.text}", None
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", None