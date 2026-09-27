**GAMIFY TO-DO APP WITH LOCAL AI INTEGRATED**

---

**DOWNLOAD THE APP (NO PYTHON REQUIRED):**

---

Download the package that matches the computer from the latest GitHub Release:

- **Windows 10/11 (64-bit):** `TODO-App-Windows-x64.zip`, then run `todo.exe`
- **Mac with Apple Silicon (M1/M2/M3/M4):** `TODO-App-macOS-Apple-Silicon.zip`
- **Mac with an Intel processor:** `TODO-App-macOS-Intel.zip`
- **Linux (64-bit):** `TODO-App-Linux-x64.tar.gz`

Python and pip are embedded in these downloads. A Windows `.exe` is a Windows-only
program and cannot run on a Mac. macOS users must download one of the `.app`
packages above.

The current macOS builds are not Apple-notarized. On first launch, macOS may require
right-clicking **TODO App**, choosing **Open**, and confirming. Fully removing this
warning requires signing and notarizing releases with an Apple Developer ID.

Linux users can extract the archive and run:

```bash
chmod +x todo
./todo
```

**RUNNING FROM SOURCE (DEVELOPERS ONLY):**

- Install Python 3.13 or later.
- Run `python -m pip install -r requirements-desktop.txt`.
- Run `python todo.py`.

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

1. Open the latest GitHub Release.
2. Download the package for your operating system and processor.
3. Extract it and launch `todo.exe`, `TODO App.app`, or `todo` as described above.

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

**For Phala Cloud CVM**

1. Create a CVM at https://phala.com/
2. Install Python packages: `pip install requests cryptography`
3. Set up endpoints in "Configure Endpoints" in the app's Phala CVM menu
4. Test the connection to make sure everything works

**For shared Web + Desktop Accounts**

1. Set `JWT_SECRET` and `WEB_SECRET_KEY` to separate strong random values in the CVM environment.
2. For email/password accounts, open the web app's Sign In page or select `Phala CVM → Sign In / Account` in the desktop app.
3. Set `SMTP_ENABLED=true`, `SMTP_USER=kylenguyen1206@gmail.com`, and a Gmail App Password as `SMTP_PASSWORD`. New accounts must enter the six-digit code sent to their email before they can sign in.

---

**NOTES:**

---

**Graceful Degradation:**

- If AI dependencies are missing, the AI tab will show installation instructions
- If MySQL dependencies are missing, sharing features will be disabled but clearly indicated
- If CVM dependencies are missing, CVM features will be disabled but app functions normally
- The app never crashes due to missing optional dependencies

**For the first time running with MySQL:**

- Run "Test Connection" in "Configure MySQL Connection" to create the todoapp database
- Enable MySQL Sharing to start using LAN features
  - If there are errors pop up, it is because the app was checking for first time run and creating files that is needed for the app to run properly.

- The app checks for updates. Windows can update in place; macOS and Linux open the
  release page so the user can replace the app with the correct native package.

**CREATING A RELEASE:**

The GitHub Actions workflow builds four self-contained packages on native runners:
Windows x64, macOS Intel, macOS Apple Silicon, and Linux x64. Push a version tag to
build the packages and attach them to a GitHub Release, for example:

```bash
git tag v1.8.0
git push origin v1.8.0
```

---

**WHAT CAN THE APP DO:**

---

- Add, Remove, Finish, Edit Tasks Manually or through AI
- Keep records of levels, number of current tasks and number of completed tasks
- Keep records of tasks locally in sorted order (default: increase in due date sorted)
- Able to upload files for context to AI
- Able to start on window startup
- Share tasks on LAN through MySQL
- Calendar view for daily tasks and todo tasks
- Store tasks encrypted on confidential cloud infrastructure
- Run AI queries privately without 3rd-party exposure
- Decentralized P2P task sharing
- Scheduled automation and reminders
- Hybrid setup combining local and cloud storage
- Auto update

---

WHAT CAN THE APP DO IN THE FUTURE:

---

- Please let me know! For now the app is at its finest.

<img width="1918" height="1017" alt="image" src="https://github.com/user-attachments/assets/3e84bfce-c935-4df7-9a82-e2f62e20a4a6" />

<img width="1918" height="1017" alt="image" src="https://github.com/user-attachments/assets/b3403f0c-00ac-453d-9ab7-045ccb77ddba" />
