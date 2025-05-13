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
        self.check_for_updates()
    
    def get_current_version(self):
        try:
            with open(self.version_file, "r") as f:
                return f.read().strip()
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
            repo_name = "todoapp"            # Change this to your repo name
            
            api_url = f"https://api.github.com/repos/{github_username}/{repo_name}/releases/latest"
            response = requests.get(api_url)
            
            if response.status_code == 200:
                latest_release = json.loads(response.text)
                latest_version = latest_release["tag_name"].replace("v", "")
                
                if self.is_newer_version(latest_version, self.current_version):
                    self.prompt_update(latest_version, latest_release["assets"][0]["browser_download_url"])
        except Exception as e:
            print(f"Update check failed: {e}")
    
    def is_newer_version(self, latest, current):
        # Simple version comparison (assumes format like "1.2.3")
        latest_parts = [int(x) for x in latest.split(".")]
        current_parts = [int(x) for x in current.split(".")]
        
        for i in range(max(len(latest_parts), len(current_parts))):
            latest_part = latest_parts[i] if i < len(latest_parts) else 0
            current_part = current_parts[i] if i < len(current_parts) else 0
            
            if latest_part > current_part:
                return True
            elif latest_part < current_part:
                return False
        
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
                # Save to a temporary file
                temp_file = str(Path.home()) + "/TODOapp/update.exe"
                with open(temp_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                # Update version file
                with open(self.version_file, "w") as f:
                    f.write(new_version)
                
                # Run the installer and exit current app
                subprocess.Popen([temp_file])
                sys.exit()
        except Exception as e:
            messagebox.showerror("Update Failed", f"Failed to update: {str(e)}")

if __name__ == "__main__":
    Updater()
