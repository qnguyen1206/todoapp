**GAMIFY TO-DO APP WITH LOCAL AI INTEGRATED**

---

**REQUIREMENTS TO RUN THE APP:**

---

**CORE REQUIREMENTS (Always Required):**

- Python 3.13 (or later) - Download from https://www.python.org/

**OPTIONAL FEATURES:**

**(1) AI Assistant Features (Optional)**

- Ollama (Local LLM runtime) - Download from https://ollama.ai/download
- Python packages: `pip install requests pillow`

If you have Ollama:

- Make sure you have a model installed (e.g., `ollama pull deepseek-r1:14b`)
- You can have multiple models installed:
  - Change the `self.current_ai_model` variable in the `ai_assistant.py` file to the model you want to use.
  - Add more models to the `self.available_models` list to add more models to the AI interface.

**(2) MySQL/LAN Sharing Features (Optional)**

- MySQL Server - Download from https://dev.mysql.com/downloads/installer/
- Python packages: `pip install mysql-connector-python keyring`

**IMPORTANT:** The app will run perfectly fine for local task management even without AI or MySQL features!

---

**HOW TO RUN THE APP:**

---

**QUICK START (Minimal Setup):**

1. Download the latest version from GitHub Release
2. Extract the folder
3. Run the `todo.exe` file or `python todo.py`

**The app will work immediately for local task management!**

**OPTIONAL SETUP (For Full Features):**

**For AI Assistant:**

1. Install Ollama from https://ollama.ai/download
2. Install Python packages: `pip install requests pillow`
3. Download a model: `ollama pull deepseek-r1:14b`
4. Start Ollama service
5. Restart the TODO app

**For MySQL/LAN Sharing:**

1. Install MySQL from https://dev.mysql.com/downloads/installer/
2. Install Python packages: `pip install mysql-connector-python keyring`
3. Start MySQL WorkBench and MySQL Server
4. Use "Configure MySQL Connection" in the app's Share menu
5. Test the connection to create the todoapp database

---

**NOTES:**

---

**Graceful Degradation:**

- If AI dependencies are missing, the AI tab will show installation instructions
- If MySQL dependencies are missing, sharing features will be disabled but clearly indicated
- The app never crashes due to missing optional dependencies

**For the first time running with MySQL:**

- Run "Test Connection" in "Configure MySQL Connection" to create the todoapp database
- Enable MySQL Sharing to start using LAN features

  - If there are errors pop up, it is because the app was checking for first time run and creating files that is needed for the app to run properly.

- The app will automatically check for updates and prompt the user to update if a new version is available.

---

**WHAT CAN THE APP DO:**

---

- Add, Remove, Finish, Edit Tasks Manually or through AI
- Keep records of levels, number of current tasks and number of completed tasks
- Keep records of tasks locally in sorted order (default: increase in due date sorted)
- Able to upload files for context to AI
- Able to start on window startup
- Share tasks on LAN through MySQL
- Auto update

---

WHAT CAN THE APP DO IN THE FUTURE:

---

- Please let me know! For now the app is at its finest.

<img width="1918" height="1017" alt="image" src="https://github.com/user-attachments/assets/3e84bfce-c935-4df7-9a82-e2f62e20a4a6" />

<img width="1918" height="1017" alt="image" src="https://github.com/user-attachments/assets/b3403f0c-00ac-453d-9ab7-045ccb77ddba" />
