import os
import requests
import sys
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
import json
import subprocess

class Updater:
    def __init__(self):
        self.version_file = str(Path.home()) + "/TODOapp/version.txt"
        self.current_version = self.get_current_version()
        print(self.current_version)
        self.check_for_updates()
    
    def get_current_version(self):
        try:
            with open(self.version_file, "r") as f:
                version = f.read().strip()
                # Clean up version string
                parts = []
                for part in version.split('.'):
                    if part.isalpha():
                        parts.append(part)                 # keep “dev”
                    else:
                        # pull out any leading digits (or default to "0")
                        num = ''.join(c for c in part if c.isdigit()) or '0'
                        parts.append(num)
                return '.'.join(parts[:3])  # Limit to 3 components
        except FileNotFoundError:
            # Create version file if it doesn't exist
            os.makedirs(os.path.dirname(self.version_file), exist_ok=True)
            with open(self.version_file, "w") as f:
                f.write("0.0.0")
            return "0.0.0"
    
    def check_for_updates(self):
        try:
            # Replace with your actual GitHub repo API URL
            github_username = "Kairu1206"  # Change this to your GitHub username
            repo_name = "todoapp"          # Change this to your repo name
            
            api_url = f"https://api.github.com/repos/{github_username}/{repo_name}/releases/latest"
            response = requests.get(api_url)
            
            if response.status_code == 200:
                latest_release = json.loads(response.text)
                latest_version = latest_release["tag_name"].lstrip("v")
                
                if self.is_newer_version(latest_version, self.current_version):
                    self.prompt_update(latest_version, latest_release["assets"][0]["browser_download_url"])
        except Exception as e:
            print(f"Update check failed: {e}")
    
    def is_newer_version(self, latest, current):
        # More robust version comparison that handles invalid version formats
        try:
            # Clean up version strings and ensure they're valid
            latest = latest.strip()
            current = current.strip()
            
            # Handle empty version strings
            if not latest or not current:
                return False
                
            # Split version strings into components
            latest_parts = latest.split(".")
            current_parts = current.split(".")
            
            # Convert parts to integers, handling non-numeric parts
            latest_nums = []
            for part in latest_parts:
                try:
                    latest_nums.append(int(part))
                except ValueError:
                    latest_nums.append(0)  # Non-numeric parts become 0
                    
            current_nums = []
            for part in current_parts:
                try:
                    current_nums.append(int(part))
                except ValueError:
                    current_nums.append(0)  # Non-numeric parts become 0
            
            # Compare version components
            for i in range(max(len(latest_nums), len(current_nums))):
                latest_part = latest_nums[i] if i < len(latest_nums) else 0
                current_part = current_nums[i] if i < len(current_nums) else 0
                
                if latest_part > current_part:
                    return True
                elif latest_part < current_part:
                    return False
            
            return False
        except Exception as e:
            print(f"Version comparison error: {e}")
            return False
    
    def prompt_update(self, new_version, download_url):
        root = tk.Tk()
        root.withdraw()  # Hide the main window
        
        if messagebox.askyesno("Update Available", 
                              f"Version {new_version} is available. Update now?"):
            self.download_and_install(download_url, new_version)
        
        root.destroy()
    
    def download_and_install(self, url, new_version):
        try:
            # Download the new version
            response = requests.get(url, stream=True)
            if response.status_code == 200:
                # Determine if it's a zip file
                is_zip = url.lower().endswith('.zip')
                
                # Save to a temporary file
                download_path = str(Path.home()) + "/TODOapp/"
                temp_file = download_path + ("update.zip" if is_zip else "update.exe")
                
                with open(temp_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                # Update version file
                with open(self.version_file, "w") as f:
                    f.write(new_version)
                
                # Create a cleanup script that will run after the app exits
                cleanup_script = download_path + "cleanup.py"
                
                # Use raw strings or forward slashes for file paths to avoid escape sequence issues
                temp_file_path = temp_file.replace("\\", "/")
                cleanup_script_path = cleanup_script.replace("\\", "/")
                
                with open(cleanup_script, "w") as f:
                    f.write(f"""
import os
import time
import sys
from pathlib import Path

# Wait a moment for the original process to exit
time.sleep(2)

# Files to clean up
files_to_remove = [
    r"{temp_file_path}",
    r"{cleanup_script_path}"
]

# Remove each file
for file_path in files_to_remove:
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Removed: {{file_path}}")
    except Exception as e:
        print(f"Failed to remove {{file_path}}: {{e}}")
""")
                
                # If it's a zip file, extract it
                if is_zip:
                    import zipfile
                    with zipfile.ZipFile(temp_file, 'r') as zip_ref:
                        zip_ref.extractall(download_path)
                    # Look for the exe file
                    exe_file = download_path + "todo.exe"
                    # Run the installer and exit current app
                    subprocess.Popen([exe_file])
                    # Run cleanup script in background
                    subprocess.Popen([sys.executable, cleanup_script], 
                                     creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    # Run the installer and exit current app
                    subprocess.Popen([temp_file])
                    # Run cleanup script in background
                    subprocess.Popen([sys.executable, cleanup_script],
                                     creationflags=subprocess.CREATE_NO_WINDOW)
                
                sys.exit()
        except Exception as e:
            messagebox.showerror("Update Failed", f"Failed to update: {str(e)}")

if __name__ == "__main__":
    Updater()






