import flet as ft
import google.generativeai as genai
import psycopg2
from psycopg2 import sql
import threading
import time
import datetime

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

# Create or update the notes table to include the topic column
cur.execute('''
    CREATE TABLE IF NOT EXISTS notes (
        id SERIAL PRIMARY KEY,
        topic TEXT NOT NULL,
        content TEXT NOT NULL
    )
''')
conn.commit()

# Check if the topic column exists, and add it if not
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='notes' AND column_name='topic'")
result = cur.fetchone()
if not result:
    cur.execute('ALTER TABLE notes ADD COLUMN topic TEXT NOT NULL')
    conn.commit()

class Message():
    def __init__(self, user: str, text: str):
        self.user = user
        self.text = text
        response = model.generate_content(text)
        self.response_text = response.text
        
def check_deadlines():
    while True:
        try:
            cur.execute("SELECT name, deadline FROM tasks WHERE deadline <= %s", 
                        (datetime.date.today() + datetime.timedelta(days=1),))
            tasks = cur.fetchall()
            for task in tasks:
                print(f"Reminder: The deadline for task '{task[0]}' is approaching on {task[1]}")
            time.sleep(86400)  # Check every 24 hours
        except Exception as e:
            print(f"Error checking deadlines: {e}")
            time.sleep(60)  # Retry after 1 minute if there's an error


def main(page: ft.Page):
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
            if new_message.value:
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
        note_topic = ft.TextField(expand=True, hint_text="Topic name")
        note_content = ft.TextField(expand=True, hint_text="Note content")
        
        def load_notes():
            try:
                note_list.controls.clear()
                cur.execute("SELECT id, topic, content FROM notes")
                for note in cur.fetchall():
                    note_list.controls.append(
                        ft.Row([
                            ft.TextButton(
                                f"Topic: {note[1]} - Note: {note[2]}",
                                on_click=lambda e, note_id=note[0], note_topic=note[1], note_content=note[2]: ask_about_note(note_id, note_topic, note_content)
                            ),
                            ft.IconButton(icon=ft.icons.DELETE, on_click=lambda e, note_id=note[0]: delete_note(note_id))
                        ])
                    )
                page.update()
            except Exception as e:
                print(f"Error loading notes: {e}")
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
        
        def delete_note(note_id):
            try:
                cur.execute(sql.SQL("DELETE FROM notes WHERE id = %s"), [note_id])
                conn.commit()
                load_notes()
            except Exception as e:
                print(f"Error deleting note: {e}")
                conn.rollback()
        
        def ask_about_note(note_id, note_topic, note_content):          
            message = f"Explain me more about {note_topic} where content is {note_content}"
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
            ft.Tab(text="Chat", content=build_chat_tab()),
            ft.Tab(text="Tasks", content=build_tasks_tab()),
            ft.Tab(text="Notes", content=build_notes_tab())
        ],
        expand=True
    )

    page.add(tabs)

ft.app(target=main)
