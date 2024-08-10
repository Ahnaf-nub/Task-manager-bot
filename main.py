import flet as ft
import google.generativeai as genai
import psycopg2
from psycopg2 import sql
import threading
import time
import datetime
import base64
import plyer
import os
from flet.auth import OAuthProvider
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
# Gemini Part
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

# Create the tasks table if it doesn't exist
cur.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        deadline DATE NOT NULL
    )
''')
conn.commit()

# Ensure the notes table includes the image column
cur.execute('''
    CREATE TABLE IF NOT EXISTS notes (
        id SERIAL PRIMARY KEY,
        topic TEXT NOT NULL,
        content TEXT NOT NULL,
        image BYTEA
    )
''')
conn.commit()

# Add the image column if it doesn't exist
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='notes' AND column_name='image'")
result = cur.fetchone()
if not result:
    cur.execute('ALTER TABLE notes ADD COLUMN image BYTEA')
    conn.commit()

class Message:
    def __init__(self, user: str, text: str):
        self.user = user
        self.text = text
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
            #print(f"Error checking deadlines: {e}")
            time.sleep(60)  # Retry after 1 minute if there's an error

def verify_google_token(token):
    try:
        id_info = id_token.verify_oauth2_token(token, google_requests.Request())
        if id_info['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            raise ValueError('Invalid token')
        return id_info
    except ValueError as e:
        print(f"Error verifying Google token: {e}")
        return None

def main(page: ft.Page):
    selected_image = None
    
    provider = OAuthProvider(
        client_id=os.getenv("GMAIL_CLIENT_ID"),
        client_secret=os.getenv("GMAIL_CLIENT_SECRET"),
        authorization_endpoint="https://accounts.google.com/o/oauth2/auth",
        token_endpoint="https://accounts.google.com/o/oauth2/token",
        user_endpoint="https://www.googleapis.com/oauth2/v1/userinfo",
        user_scopes=["https://www.googleapis.com/auth/userinfo.email"],
        user_id_fn=lambda u: u["id"],
        redirect_url="http://localhost:8550/oauth_callback",
    )
    def login_click(e):
        page.login(provider)

    def on_login(e):
        if e.error:
            raise Exception(e.error)
        print("User ID:", page.auth.user.id)
        print("Access token:", page.auth.token.access_token)

    page.on_login = on_login
    page.add(ft.ElevatedButton("Login with Gmail", on_click=login_click))
    def on_file_picked(e):
        nonlocal selected_image
        if e.files:
            selected_image = e.files[0].read_bytes()
            print(f"Image selected: {e.files[0].name}, Size: {len(selected_image)} bytes")

    file_picker = ft.FilePicker()
    file_picker.on_change = on_file_picked

    page.overlay.append(file_picker) 

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
                cur.execute("SELECT id, topic, content, image FROM notes")
                notes = cur.fetchall()
                note_list.controls.clear()
                for note in notes:
                    note_controls = [ft.Text(f"{note[1]}: {note[2]}")]
                    if note[3]:
                        print(f"Note {note[0]} has an image.")
                        image_data = note[3] if note[3] else None
                        image_src = f"data:image/png;base64,{image_data}" if image_data else None
                        image_preview = ft.Image(src=image_src, fit=ft.ImageFit.contain, width=100, height=100)
                        view_image_button = ft.ElevatedButton("View Image", on_click=lambda e, image_src=image_src: view_image(image_src))
                        note_controls.extend([image_preview, view_image_button])
                    else:
                        print(f"Note {note[0]} does not have an image.")
                        image_preview = ft.Text("No Image")
                        note_controls.append(image_preview)
                    note_controls.append(ft.ElevatedButton("Delete", on_click=lambda e, note_id=note[0]: delete_note(note_id)))
                    note_controls.append(ft.ElevatedButton("Ask", on_click=lambda e, note_id=note[0], note_topic=note[1], note_content=note[2]: ask_about_note(note_id, note_topic, note_content)))
                    note_list.controls.append(ft.Row(note_controls))
                page.update()
            except Exception as e:
                print(f"Error loading notes: {e}")
                conn.rollback()

        def add_note_click(e):
            nonlocal selected_image
            try:
                if note_topic.value and note_content.value:
                    image_data = selected_image if selected_image else None
                    cur.execute(
                        sql.SQL("INSERT INTO notes (topic, content, image) VALUES (%s, %s, %s)"),
                        [note_topic.value, note_content.value, image_data]
                    )
                    conn.commit()
                    print("Note added successfully")
                    load_notes()
                    note_topic.value = ""
                    note_content.value = ""
                    selected_image = None
                    page.update()
                else:
                    print("Note topic or content is missing")
            except Exception as e:
                print(f"Error adding note: {e}")
                conn.rollback()

        def delete_note(note_id):
            try:
                cur.execute(sql.SQL("DELETE FROM notes WHERE id = %s"), [note_id])
                conn.commit()
                load_notes()
            except Exception as e:
                print(f"Error deleting note: {e}")
                conn.rollback()

        def ask_about_note(note_id, note_topic, note_content):
            message = f"Tell me more about {note_topic}: {note_content}"
            page.pubsub.send_all(Message(user=page.session_id, text=message))
            tabs.selected_index = 0
            page.update()

        def view_image(image_src):
            print(f"Viewing image: {image_src}")
            page.dialog = ft.AlertDialog(
                title=ft.Text("Image Viewer"),
                content=ft.Image(src=image_src, fit=ft.ImageFit.contain),
                actions=[ft.ElevatedButton("Close", on_click=lambda e: page.dialog.close())]
            )
            page.dialog.open = True
            page.update()

        load_notes()

        return ft.Container(
            content=ft.Column([
                note_list,
                ft.Row([note_topic, note_content, ft.IconButton(icon=ft.icons.ATTACH_FILE, on_click=lambda _: file_picker.pick_files(allow_multiple=False)), ft.ElevatedButton("Add Note", on_click=add_note_click)])
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
        expand=1
    )

    page.add(tabs)
    page.update()

# Start the deadline checking thread
deadline_thread = threading.Thread(target=check_deadlines, daemon=True)
deadline_thread.start()

ft.app(target=main)
if __name__ == "__main__":
    threading.Thread(target=check_deadlines, daemon=True).start()
    ft.app(target=main)
