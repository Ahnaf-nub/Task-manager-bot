import flet as ft
import google.generativeai as genai

GOOGLE_API_KEY = ""
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

class Message():
    def __init__(self, user: str, text: str):
        self.user = user
        self.text = text
        response = model.generate_content(text)
        self.response_text = response.text
    
def main(page: ft.Page):
    chat = ft.ListView(expand=True, spacing=10, padding=10)
    new_message = ft.TextField(expand=True)
    
    def on_message(message: Message):
        chat.controls.append(ft.Text(f"{message.user}: {message.text}"))
        chat.controls.append(ft.Text(f"Bot: {message.response_text}"))
        page.update()

    page.pubsub.subscribe(on_message)    

    def send_click(e):
        page.pubsub.send_all(Message(user=page.session_id, text=new_message.value))
        #print(new_message.value)
        if new_message.value:
            new_message.value = ""
        page.update()
    
    page.add(
        ft.Container(
            content=ft.Column([
                chat,
                ft.Row([new_message, ft.ElevatedButton("Send", on_click=send_click)])
            ]),
            expand=True,
            padding=10
        )
    )

ft.app(target=main)

