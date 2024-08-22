import flet as ft
import google.generativeai as genai
import psycopg2
from psycopg2 import sql
import threading
import time
import datetime
import plyer
import bcrypt

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


class Message:
    def __init__(self, user: str, text: str):
        self.user = user
        response = model.generate_content(text)
        self.response_text = response.text


def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def check_password(hashed_password, user_password):
    pwhash = bcrypt.hashpw(user_password.encode('utf8'), bcrypt.gensalt())
    password_hash = pwhash.decode('utf8') # decode the hash to prevent it from being encoded twice
    return password_hash == hashed_password

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


def register_user(username, email, password):
    try:
        # Hash the password and store it as bytes
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        cur.execute(
            sql.SQL("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)"),
            [username, email, hashed_password]  # Store the hashed password as bytes
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
            hashed_password = user[1]
            if bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8')):
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
            task_deadline = ft.TextField(expand=True, hint_text="Deadline (YYYY-MM-DD)")

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
            note_content = ft.TextField(expand=True, hint_text="Note content")

            def load_notes():
                try:
                    note_list.controls.clear()
                    cur.execute("SELECT id, topic, content FROM notes")
                    for note in cur.fetchall():
                        note_list.controls.append(
                            ft.ListTile(
                                title=ft.Text(note[1]),
                                subtitle=ft.Text(f"{note[1]}: {note[2]}"),
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

        logout_button = ft.ElevatedButton("Logout", on_click=lambda e: logout_click(e, page))
        page.add(ft.Column([logout_button, tabs]))
        threading.Thread(target=check_deadlines, daemon=True).start()

ft.app(target=main)
