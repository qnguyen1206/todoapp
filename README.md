**GAMIFY TO-DO APP WITH LOCAL AI INTEGRATED**

![todo_app_screenshot](https://github.com/user-attachments/assets/d5f753cc-e73a-4689-91d6-2174f9b166cb)


________________________________
**REQUIREMENTS TO RUN THE APP:**
________________________________

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

________________________
**HOW TO RUN THE APP:**
________________________

**STEP 1**

- Download the lastest version of the app from GitHub Release
- Extract the folder

**STEP 2**

- Run Ollama
- Run MySQL WorkBench
- Run MySQL Server

**STEP 3**

- Run the todo.exe file

_________________
**NOTES:**
_________________

**For the first time running the app**

  - User will need to run "Test Connection" in "Config MySQL Connection" or "Enable MySQL Sharing" in order to create the todoapp table if the user wants to use the LAN sharing feature.
  - If there are errors pop up, it is because the app was checking for first time run and creating files that is needed for the app to run properly.

- The app will automatically check for updates and prompt the user to update if a new version is available.

_________________________
**WHAT CAN THE APP DO:**
_________________________

- Add, Remove, Finish, Edit Tasks Manually or through AI
- Keep records of levels, number of current tasks and number of completed tasks
- Keep records of tasks locally in sorted order (default: increase in due date sorted)
- Able to upload files for context to AI
- Able to start on window startup
- Share tasks on LAN through MySQL
- Auto update

_________________________________

WHAT CAN THE APP DO IN THE FUTURE:
__________________________________

- Please let me know! For now the app is at its finest.
