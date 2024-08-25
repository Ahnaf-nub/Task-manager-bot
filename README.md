# Task Manager and Helper Bot
This project is a comprehensive task management and AI-driven chatbot application built using Python, PostgreSQL, and Flet for the user interface. It allows users to manage tasks, take notes, and interact with a generative AI model for assistance. The application also features a user authentication system, push notifications for upcoming deadlines, and more.

Key Features:
User Authentication: Secure account creation and login functionality with password hashing using passlib and data storage in PostgreSQL.

**Task Management**: Add, view, and delete tasks with deadlines. The app sends push notifications to remind users of upcoming deadlines of their added tasks.

**Notes Management**: Create, view, and delete personal notes for easy organization of ideas and tasks.

**AI Chatbot Integration**: Interact with a generative AI model powered by Google’s Gemini API for task-related queries and assistance.


**Push Notifications**: Real-time reminders using plyer to notify users of approaching task deadlines.

**Responsive UI**: A clean and responsive user interface built with Flet, providing seamless interaction across devices.
### Technologies Used:
**Python**: Core language for application logic.

**PostgreSQL**: Relational database for securely storing user data, tasks, and notes.

**Flet**: Framework for building the application interface.

**Google Gemini API**: For AI-driven conversational capabilities.

**passlib**: For secure password hashing and verification.

**plyer**: For cross-platform push notifications.

## For running Locally

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/Ahnaf-nub/Functionally_Dysfunctional_Text_Editor.git
   cd functionally-dysfunctional-text-editor
2. **Install the dependencies**
   ```
   pip install -r requirements.txt
3. **Run the main file**
   ```
   python main.py
