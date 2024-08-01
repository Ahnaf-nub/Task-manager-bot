import flet as ft
import google.generativeai as genai
import psycopg2
from psycopg2 import sql

# Configure the generative AI
GOOGLE_API_KEY = ""
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

DB_HOST = "localhost"
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASSWORD = "password"

# Connect to PostgreSQL
conn = psycopg2.connect(
    host=DB_HOST,
    database=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD
)
cur = conn.cursor()

cur.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        deadline DATE NOT NULL
    )
''')
conn.commit()

class Message():
    def __init__(self, user: str, text: str):
        self.user = user
        self.text = text
        response = model.generate_content(text)
        self.response_text = response.text

def main(page: ft.Page):
    def build_chat_tab():
        chat = ft.ListView(expand=True, spacing=10, padding=10, auto_scroll=True)
        new_message = ft.TextField(expand=True, hint_text="Type your message here...")
        
        def on_message(message: Message):
            chat.controls.append(ft.Text(f"{message.user}: {message.text}"))
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
        task_deadline = ft.TextField(expand=True, hint_text="Task deadline")
        def delete_task_click(e):
            try:
                selected_task = task_list.selected_control
                if selected_task:
                    task_name = selected_task.text.split(" - ")[0].split(": ")[1]
                    cur.execute(
                        sql.SQL("DELETE FROM tasks WHERE name = %s"),
                        [task_name]
                    )
                    conn.commit()
                    load_tasks()
                    page.update()
            except Exception as e:
                print(f"Error deleting task: {e}")
                conn.rollback()

        delete_button = ft.ElevatedButton("Delete Task", on_click=delete_task_click)
        task_list.controls.append(delete_button)
        def load_tasks():
            try:
                task_list.controls.clear()
                cur.execute("SELECT name, deadline FROM tasks")
                for task in cur.fetchall():
                    task_list.controls.append(ft.Text(f"Task: {task[0]} - Deadline: {task[1]}"))
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

        load_tasks()
        
        return ft.Container(
            content=ft.Column([
                task_list,
                ft.Row([task_name, task_deadline, ft.ElevatedButton("Add Task", on_click=add_task_click)])
            ]),
            expand=True,
            padding=10
        )
    
    tabs = ft.Tabs(
        selected_index=0,
        tabs=[
            ft.Tab(text="Chat", content=build_chat_tab()),
            ft.Tab(text="Tasks", content=build_tasks_tab())
        ],
        expand=True
    )

    page.add(tabs)

ft.app(target=main)

