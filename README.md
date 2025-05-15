____________________________________
**REQUIREMENTS TO RUN THE APP:**
____________________________________
**(1) Have LLMs or AIs locally, if not, please get one from Ollama**

  - If you don't have Ollama, you can download it from https://ollama.ai/download
  - If you have Ollama, make sure you have the "[your models name]" model installed
    - You can install it by running the command `ollama run [your models name]` in your terminal
    - If you get an error, please run the command `ollama pull [your models name]` in your terminal
    - You can have multiple models installed:
      - Change the `self.current_ai_model` variable in the `todo.py` file to the model you want to use.
      - Add more models to the `self.available_models` list in the `todo.py` file to add more models to the AI Model menu in the app.

**(2) Have MySQL installed and running (for LAN sharing)**

  - If you don't have MySQL, you can download it from https://dev.mysql.com/downloads/installer/

**(3) Python 3.13 (or later)**
  - If you don't have Python 3.13 or above, you can download it from https://www.python.org/

____________________________________
**HOW TO RUN THE APP:**
____________________________________

**STEP 1 /!\\ THIS STEP IS VERY IMPORTANT. PLEASE FOLLOW IT CORRECTLY /!\\**
  - Download the lastest version of the app from GitHub Release
  - Extract the folder
  - Go into the folder
  - Change the name of the inside folder to "TODOapp"
    
  - Expected Structure Before:
    - todoapp-1.2.3 → todoapp-1.2.3 → [source code]
  - Expected Structure After:
    - todoapp-1.2.3 → TODOapp → [source code]
    
**STEP 2**
  - Run Ollama
  - Run MySQL WorkBench
  - Run MySQL Server
    
**STEP 3**
  - Run the app

____________________________________
**NOTES:**
____________________________________

**Problem 1**

*Description*

- When you first run the app and the version will be 0.0.0.

*Fix*

- This is the default value when the app is first install in order to maintain the lowest possible version for the auto updater to work.
- Currently working on the fix for the auto updater.

**Problem 2**

*Description*

- App throwing error "todoapp table does not exist" or something similar.

*Fix*

- This error is thrown on the first run because the local machine does not have the table.
- Run "Test Connection" in "Config MySQL Connection". This will create a new todoapp table.
- Currently working on the fix for this create table problem.

____________________________________
**WHAT CAN THE APP DO:**
____________________________________

- Add, Remove, Finish, Edit Tasks Manually or through AI
- Keep records of levels, number of current tasks and number of completed tasks
- Keep records of tasks locally in sorted order (default: increase in due date sorted)
- Able to upload files for context to AI
- Able to start on window startup
- Share tasks on LAN through MySQL

____________________________________
WHAT CAN THE APP DO IN THE FUTURE:
____________________________________

- Keep records of what tasks have been done
- Better UI including level progress bar and more settings for personal preferences
- Something fun for more engagment
