**GAMIFY TODO APP WITH AI INTEGRATED**

- **THIS IS A PERSONAL PROJECTS SIMPLE GAMIFY TODO APP THAT HAVE DEEPSEEK-R1 14B PARAM INTEGRATE.**

REQUIREMENTS TO RUN THE APP:

- Have LLMs or AIs locally, if not, please get one from Ollama

  - If you don't have Ollama, you can download it from https://ollama.ai/download
  - If you have Ollama, please make sure you have the "[your models name]" model installed
    - You can install it by running the command `ollama run [your models name]` in your terminal
    - If you get an error, please run the command `ollama pull [your models name]` in your terminal
    - You can have multiple models installed:
      - Change the `self.current_ai_model` variable in the `todo.py` file to the model you want to use.
      - Add more models to the `self.available_models` list in the `todo.py` file to add more models to the AI Model menu in the app.

- Have MySQL installed and running (for LAN sharing)

  - If you don't have MySQL, you can download it from https://dev.mysql.com/downloads/installer/
  - Please follow the instructions in the app to install and configure MySQL:

    - MySQL Installation Guide
      The MySQL sharing feature requires MySQL Server to be installed and running on your computer.
      Follow these steps to install MySQL:

      1. Download MySQL Installer:

      - Go to https://dev.mysql.com/downloads/installer/
      - Download the MySQL Installer for Windows

      2. Run the installer:

      - Choose "Custom" installation
      - Select at minimum:
        - MySQL Server
        - MySQL Workbench (optional but recommended)
      - Click "Next" and follow the installation steps

      3. Configure MySQL Server:

      - Use the recommended defaults
      - Set a root password (remember this password!)
      - Create a user account if prompted
      - Make sure "Configure MySQL Server as a Windows Service" is selected
      - Ensure "Start the MySQL Server at System Startup" is checked

      4. Verify MySQL is running:

      - Open Services (search for "services" in Windows search)
      - Look for "MySQL" in the list
      - Status should show "Running"
      - If not running, right-click and select "Start"

      5. Configure TODO App:

      - Return to the TODO App
      - Go to Options → Configure MySQL
      - Enter your MySQL credentials:
        - Host: localhost
        - User: root (or the user you created)
        - Password: (the password you set)
        - Database: todoapp (this will be created automatically)

      6. Enable MySQL sharing:

      - Go to Options → Enable MySQL Sharing

      Troubleshooting:

      - If you get "Access denied" errors, check your username and password
      - If you get "Can't connect to MySQL server" errors, make sure the MySQL service is running
      - If you installed MySQL previously, you may need to reset your root password

      Need more help? Visit:
      https://dev.mysql.com/doc/mysql-installation-excerpt/8.0/en/

- Python 3.13 (or later)

WHAT CAN THE APP DO:

- Add, Remove, Finish, Edit Tasks Manually or through AI
- Keep records of levels, number of current tasks and number of completed tasks
- Keep records of tasks locally in sorted order (default: increase in due date sorted)
- Able to upload files for context to AI
- Able to start on window startup
- Share tasks on LAN through MySQL

WHAT CAN THE APP DO IN THE FUTURE:

- Keep records of what tasks have been done
- Better UI including level progress bar and more settings for personal preferences
- Something fun for more engagment
