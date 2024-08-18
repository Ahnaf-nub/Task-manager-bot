import flet as ft
import google.generativeai as genai
import psycopg2
from psycopg2 import sql
import threading
import time
import datetime
import plyer
import os
import firebase_admin
from firebase_admin import credentials, auth

# Initialize Firebase Admin SDK
cred = credentials.Certificate("C:/Users/abidu\OneDrive/Documents/idkf/tas_reminder/cred.json")
firebase_admin.initialize_app(cred)

# Google API Key
GOOGLE_API_KEY = ""
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# PostgreSQL connection details
DB_HOST = "localhost"
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASSWORD = "Ahnafhaq12345"

conn = psycopg2.connect(
    host=DB_HOST,
    database=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD
)
cur = conn.cursor()

# Create the tasks table if it doesn't exist
cur.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        deadline DATE NOT NULL
    )
''')
conn.commit()

# Ensure the notes table exists
cur.execute('''
    CREATE TABLE IF NOT EXISTS notes (
        id SERIAL PRIMARY KEY,
        topic TEXT NOT NULL,
        content TEXT NOT NULL
    )
''')
conn.commit()

class Message:
    def __init__(self, user: str, text: str):
        self.user = user
        response = model.generate_content(text)
        self.response_text = response.text

def notify(title: str, message: str):
    plyer.notification.notify(
        app_name="Task reminder",
        title=title,
        message=message,
        timeout=10,    
    )

def check_deadlines():
    while True:
        try:
            cur.execute("SELECT name, deadline FROM tasks WHERE deadline <= %s", (datetime.date.today() + datetime.timedelta(days=1),))
            tasks = cur.fetchall()
            for task in tasks:
                deadline = task[1]
                if deadline <= datetime.date.today() + datetime.timedelta(days=1):
                    notify("Reminder", f"The deadline for task '{task[0]}' is approaching on {deadline}")
            time.sleep(86400)  # Check every 24 hours
        except Exception as e:
            time.sleep(60)  # Retry after 1 minute if there's an error

def create_user(email, password):
    try:
        user = auth.create_user(
            email=email,
            password=password
        )
        return user
    except Exception as e:
        print(f"Error creating user: {e}")
        return None

def login_user(email, password):
    try:
        user = auth.get_user_by_email(email)
        return user
    except Exception as e:
        print(f"Error logging in user: {e}")
        return None

def main(page: ft.Page):
    if not page.session.get("logged_in"):
        email_input = ft.TextField(hint_text="Email")
        password_input = ft.TextField(hint_text="Password", password=True)
        
        def register_user(e):
            email = email_input.value
            password = password_input.value
            if email and password:
                user = create_user(email, password)
                if user:
                    page.session.set("logged_in", True)
                    page.session.set("user_info", {"email": email})
                    page.update()

        def login_user_func(e):
            email = email_input.value
            password = password_input.value
            if email and password:
                user = login_user(email, password)
                if user:
                    page.session.set("logged_in", True)
                    page.session.set("user_info", {"email": email})
                    page.update()

        page.add(ft.Text("Register or Login"))
        page.add(email_input)
        page.add(password_input)
        page.add(ft.ElevatedButton("Register", on_click=register_user))
        page.add(ft.ElevatedButton("Login", on_click=login_user_func))
    else:
        # Main application logic after user is authenticated
        def build_chat_tab():
            chat = ft.ListView(expand=True, spacing=10, padding=10, auto_scroll=True)
            new_message = ft.TextField(expand=True, hint_text="Type your message here...")

            def on_message(message: Message):
                chat.controls.append(ft.Text(f"User: {message.text}"))
                chat.controls.append(ft.Text(f"Bot: {message.response_text}"))
                page.update()

            page.pubsub.subscribe(on_message)

            def send_click(e):
                user_message = new_message.value
                if user_message:
                    new_message.value = ""
                    processing_text = ft.Text("Processing answer...", color="blue")
                    chat.controls.append(processing_text)
                    page.update()
                message = Message(user=page.session_id, text=user_message)
                page.pubsub.send_all(message)
                new_message.value = ""
                page.update()
            return ft.Container(
                content=ft.Column([
                    chat,
                    ft.Row([new_message, ft.ElevatedButton("Send", on_click=send_click)])
                ]),
                expand=True,
                padding=10
            )

        def build_tasks_tab():
            task_list = ft.ListView(expand=True, spacing=10, padding=10, auto_scroll=True)
            task_name = ft.TextField(expand=True, hint_text="Task name")
            task_deadline = ft.TextField(expand=True, hint_text="Deadline")

            def load_tasks():
                try:
                    task_list.controls.clear()
                    cur.execute("SELECT id, name, deadline FROM tasks")
                    for task in cur.fetchall():
                        task_list.controls.append(
                            ft.Row([
                                ft.TextButton(
                                    f"Task: {task[1]} - Deadline: {task[2]}",
                                    on_click=lambda e, task_id=task[0], task_name=task[1]: ask_about_task(task_id, task_name)
                                ),
                                ft.IconButton(icon=ft.icons.DELETE, on_click=lambda e, task_id=task[0]: delete_task(task_id))
                            ])
                        )
                    page.update()
                except Exception as e:
                    print(f"Error loading tasks: {e}")
                    conn.rollback()

            def add_task_click(e):
                try:
                    if task_name.value and task_deadline.value:
                        cur.execute(
                            sql.SQL("INSERT INTO tasks (name, deadline) VALUES (%s, %s)"),
                            [task_name.value, task_deadline.value]
                        )
                        conn.commit()
                        load_tasks()
                        task_name.value = ""
                        task_deadline.value = None
                        page.update()
                except Exception as e:
                    print(f"Error adding task: {e}")
                    conn.rollback()

            def delete_task(task_id):
                try:
                    cur.execute(sql.SQL("DELETE FROM tasks WHERE id = %s"), [task_id])
                    conn.commit()
                    load_tasks()
                except Exception as e:
                    print(f"Error deleting task: {e}")
                    conn.rollback()

            def ask_about_task(task_id, task_name):
                message = f"Help me to do this task: {task_name}"
                page.pubsub.send_all(Message(user=page.session_id, text=message))
                tabs.selected_index = 0
                page.update()

            load_tasks()

            return ft.Container(
                content=ft.Column([
                    task_list,
                    ft.Row([task_name, task_deadline, ft.ElevatedButton("Add Task", on_click=add_task_click)])
                ]),
                expand=True,
                padding=10
            )

        def build_notes_tab():
            note_list = ft.ListView(expand=True, spacing=10, padding=10, auto_scroll=True)
            note_topic = ft.TextField(hint_text="Topic")
            note_content = ft.TextField(hint_text="Content", multiline=True)

            def load_notes():
                try:
                    cur.execute("SELECT id, topic, content FROM notes")
                    notes = cur.fetchall()
                    note_list.controls.clear()
                    for note in notes:
                        note_list.controls.append(
                            ft.ListTile(
                                title=ft.Row([ft.Text(f"{note[1]}: {note[2]}")]),
                                trailing=ft.IconButton(ft.icons.DELETE, on_click=lambda e, note_id=note[0]: delete_note_click(note_id))
                            )
                        )
                    page.update()
                except Exception as e:
                    print(f"Error loading notes: {e}")
                    conn.rollback()

            def delete_note_click(note_id):
                try:
                    cur.execute(sql.SQL("DELETE FROM notes WHERE id = %s"), [note_id])
                    conn.commit()
                    load_notes()
                except Exception as e:
                    print(f"Error deleting note: {e}")
                    conn.rollback()

            def add_note_click(e):
                try:
                    if note_topic.value and note_content.value:
                        cur.execute(
                            sql.SQL("INSERT INTO notes (topic, content) VALUES (%s, %s)"),
                            [note_topic.value, note_content.value]
                        )
                        conn.commit()
                        load_notes()
                        note_topic.value = ""
                        note_content.value = ""
                        page.update()
                except Exception as e:
                    print(f"Error adding note: {e}")
                    conn.rollback()

            load_notes()

            return ft.Container(
                content=ft.Column([
                    note_list,
                    ft.Row([note_topic, note_content, ft.ElevatedButton("Add Note", on_click=add_note_click)])
                ]),
                expand=True,
                padding=10
            )

        tabs = ft.Tabs(
            tabs=[
                ft.Tab(text="Chatbot", content=build_chat_tab()),
                ft.Tab(text="Tasks", content=build_tasks_tab()),
                ft.Tab(text="Notes", content=build_notes_tab())
            ],
            selected_index=0,
            expand=1
        )

        page.add(tabs)
        threading.Thread(target=check_deadlines, daemon=True).start()

ft.app(target=main)
