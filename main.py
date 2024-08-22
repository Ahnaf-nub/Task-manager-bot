import flet as ft
import google.generativeai as genai
import psycopg2
from psycopg2 import sql
import threading
import time
import datetime
import plyer
from passlib.hash import pbkdf2_sha256

# Google API Key
GOOGLE_API_KEY = ""
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# PostgreSQL connection details
DB_HOST = "localhost"
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASSWORD = ""

conn = psycopg2.connect(
    host=DB_HOST,
    database=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD
)
cur = conn.cursor()

# Create tables if they don't exist
cur.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        deadline DATE NOT NULL
    )
''')
conn.commit()

cur.execute('''
    CREATE TABLE IF NOT EXISTS notes (
        id SERIAL PRIMARY KEY,
        topic TEXT NOT NULL,
        content TEXT NOT NULL
    )
''')
conn.commit()

cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        password BYTEA NOT NULL  -- Store passwords as binary data
    );
''')
conn.commit()

cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='notes' AND column_name='topic'")
result = cur.fetchone()
if not result:
    cur.execute('ALTER TABLE notes ADD COLUMN topic TEXT NOT NULL')
    conn.commit()

class Message:
    def __init__(self, user: str, text: str):
        self.user = user
        self.text = text
        response = model.generate_content(text)
        self.response_text = response.text

# Function to hash a password
def hash_password(password):
    return pbkdf2_sha256.hash(password)

# Function to check a password
def check_password(hashed_password, user_password):
    return pbkdf2_sha256.verify(user_password, hashed_password)

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
            print(f"Error checking deadlines: {e}")
            time.sleep(60)  # Retry after 1 minute if there's an error

def register_user(username, email, password):
    try:
        # Hash the password
        hashed_password = hash_password(password)
        cur.execute(
            sql.SQL("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)"),
            [username, email, hashed_password]  # Store the hashed password as a string
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error registering user: {e}")
        conn.rollback()
        return False


def login_user(email, password):
    try:
        cur.execute(sql.SQL("SELECT id, password FROM users WHERE email = %s"), [email])
        user = cur.fetchone()
        if user:
            user_id = user[0]
            hashed_password = user[1]  # Retrieved password as string
            if check_password(hashed_password, password):
                return user_id  # Return user id
            else:
                print("Password does not match.")
                return None
        else:
            print("User not found.")
            return None
    except Exception as e:
        print(f"Error logging in: {e}")
        return None

def handle_register(page, username, email, password):
    if register_user(username, email, password):
        page.add(ft.Text("Registration successful! You can now log in."))
    else:
        page.add(ft.Text("Registration failed. Try a different email/username."))

def handle_login(page, email, password):
    user_id = login_user(email, password)
    if user_id:
        page.session.set("logged_in", True)
        page.session.set("user_id", user_id)
        page.clean()
        main(page)  # Reload the page to show the app
    else:
        page.add(ft.Text("Login failed. Check your credentials and try again."))

def logout_click(e, page):
    page.session.remove("logged_in")
    page.session.remove("user_id")
    page.clean()
    main(page)  # Reload the page to show login/register

def main(page: ft.Page):
    if not page.session.get("logged_in"):
        # Registration form
        username = ft.TextField(label="Username")
        email = ft.TextField(label="Email")
        password = ft.TextField(label="Password", password=True)
        register_button = ft.ElevatedButton("Register", on_click=lambda e: handle_register(page, username.value, email.value, password.value))

        # Login form
        login_email = ft.TextField(label="Email")
        login_password = ft.TextField(label="Password", password=True)
        login_button = ft.ElevatedButton("Login", on_click=lambda e: handle_login(page, login_email.value, login_password.value))

        page.add(
            ft.Column([
                ft.Text("Register"),
                username,
                email,
                password,
                register_button,
                ft.Text("Login"),
                login_email,
                login_password,
                login_button
            ])
        )
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
                page.pubsub.send_all(Message(user=page.session_id, text=new_message.value))
                user_message = new_message.value
                if user_message:
                    processing_text = ft.Text("Processing answer...", color="blue")
                    chat.controls.append(processing_text)
                    page.update()
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
            note_topic = ft.TextField(expand=True, hint_text="Note topic")
            note_content = ft.TextField(expand=True, hint_text="Note content", multiline=True)

            def load_notes():
                try:
                    cur.execute("SELECT id, topic, content FROM notes")
                    notes = cur.fetchall()
                    note_list.controls.clear()
                    for note in notes:
                        note_controls = [ft.Text(f"{note[1]}: {note[2]}")]
                        note_controls.append(ft.ElevatedButton("Delete", on_click=lambda e, note_id=note[0]: delete_note_click(note_id)))
                        note_controls.append(ft.ElevatedButton("Ask", on_click=lambda e, note_id=note[0], note_topic=note[1], note_content=note[2]: ask_about_note(note_id, note_topic, note_content)))
                        note_list.controls.append(ft.Row(note_controls))
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

            def ask_about_note(note_id, note_topic, note_content):
                if note_topic and note_content:       
                    message = f"Explain me more about {note_topic} where content is {note_content}."
                    page.pubsub.send_all(Message(user=page.session_id, text=message))
                    tabs.selected_index = 0
                    page.update()
                else:
                    message = f"Explain me more about {note_topic}."
                    page.pubsub.send_all(Message(user=page.session_id, text=message))
                    tabs.selected_index = 0
                    page.update()

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
            selected_index=0,
            tabs=[
            ft.Tab(text="Chat", icon=ft.icons.CHAT, content=build_chat_tab()),
            ft.Tab(text="Tasks", icon=ft.icons.CHECK, content=build_tasks_tab()),
            ft.Tab(text="Notes", icon=ft.icons.NOTE, content=build_notes_tab())
            ],
            expand=True
        )

        logout_button = ft.ElevatedButton("Logout", on_click=lambda e: logout_click(e, page))
        page.add(tabs)
        page.add(ft.Column([logout_button]))
        threading.Thread(target=check_deadlines, daemon=True).start()

ft.app(target=main)
