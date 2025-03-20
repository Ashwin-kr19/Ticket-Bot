
import sqlite3
import os

# Constants
DB_PATH = "users.db"
SUMMARIES_DIR = "problem_summaries"

# Ensure summaries directory exists
os.makedirs(SUMMARIES_DIR, exist_ok=True)

def create_tables():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS ticket_details (
            chat_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            problem_summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (username) REFERENCES users(username)
        )''')
    conn.commit()
    conn.close()
