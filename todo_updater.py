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
        print(f"Current version: {self.current_version}")
        self.check_for_updates()
    
    def get_current_version(self):
        try:
            with open(self.version_file, "r") as f:
                version = f.read().strip()
                # Clean up version string
                parts = []
                for part in version.split('.'):
                    if part.isalpha():
                        parts.append(part)                 # keep "dev"
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
        """Compare version strings properly (e.g., 1.1.1 > 1.0.5)"""
        try:
            # Clean up version strings
            latest = latest.strip().lstrip('v')
            current = current.strip().lstrip('v')
            
            # Handle empty version strings
            if not latest or not current:
                return False
            
            # Split version strings into components
            latest_parts = latest.split(".")
            current_parts = current.split(".")
            
            # Convert parts to integers, handling non-numeric parts
            def parse_version_part(part):
                # Extract only numeric part from the beginning
                numeric_part = ""
                for char in part:
                    if char.isdigit():
                        numeric_part += char
                    else:
                        break
                return int(numeric_part) if numeric_part else 0
            
            latest_nums = [parse_version_part(part) for part in latest_parts]
            current_nums = [parse_version_part(part) for part in current_parts]
            
            # Pad shorter version with zeros (e.g., 1.1 becomes 1.1.0)
            max_length = max(len(latest_nums), len(current_nums))
            latest_nums.extend([0] * (max_length - len(latest_nums)))
            current_nums.extend([0] * (max_length - len(current_nums)))
            
            # Compare version components from left to right
            for i in range(max_length):
                if latest_nums[i] > current_nums[i]:
                    return True
                elif latest_nums[i] < current_nums[i]:
                    return False
            
            # All components are equal
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
                
                # Get current working directory (where the app files are)
                current_dir = os.getcwd()
                
                # Create a comprehensive cleanup script
                cleanup_script = download_path + "cleanup_and_update.py"
                
                # Use raw strings for file paths
                temp_file_path = temp_file.replace("\\", "/")
                cleanup_script_path = cleanup_script.replace("\\", "/")
                current_dir_path = current_dir.replace("\\", "/")
                
                with open(cleanup_script, "w") as f:
                    f.write(f'''
import os
import time
import sys
import shutil
import zipfile
from pathlib import Path

# Wait for the original process to exit
time.sleep(3)

print("Starting update process...")

# Current app directory
app_dir = r"{current_dir_path}"
download_dir = r"{download_path}"
temp_file = r"{temp_file_path}"
cleanup_script = r"{cleanup_script_path}"

try:
    # If it's a zip file, extract and update
    if temp_file.endswith('.zip'):
        print("Extracting update...")
        with zipfile.ZipFile(temp_file, 'r') as zip_ref:
            # Extract to a temporary directory first
            extract_dir = download_dir + "temp_extract/"
            zip_ref.extractall(extract_dir)
            
            # Find the new executable
            new_exe = None
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    if file.endswith('.exe') and 'todo' in file.lower():
                        new_exe = os.path.join(root, file)
                        break
                if new_exe:
                    break
            
            if new_exe:
                # Copy new exe to app directory, replacing old one
                target_exe = os.path.join(app_dir, "todo.exe")
                print(f"Copying {{new_exe}} to {{target_exe}}")
                shutil.copy2(new_exe, target_exe)
                
                # Copy any other updated files (like Python modules)
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        if file.endswith(('.py', '.json', '.txt', '.png', '.ico')) and not file.startswith('cleanup'):
                            src_file = os.path.join(root, file)
                            dst_file = os.path.join(app_dir, file)
                            try:
                                print(f"Updating {{file}}")
                                shutil.copy2(src_file, dst_file)
                            except Exception as e:
                                print(f"Could not update {{file}}: {{e}}")
                
                # Clean up temp extraction directory
                shutil.rmtree(extract_dir, ignore_errors=True)
                print("Update completed successfully!")
                
                # Start the updated application
                os.startfile(target_exe)
            else:
                print("Could not find todo.exe in the update package")
    else:
        # Direct exe file - replace the current one
        target_exe = os.path.join(app_dir, "todo.exe")
        print(f"Replacing {{target_exe}} with {{temp_file}}")
        shutil.copy2(temp_file, target_exe)
        
        print("Update completed successfully!")
        # Start the updated application
        os.startfile(target_exe)
    
    # Clean up temporary files
    files_to_remove = [temp_file, cleanup_script]
    for file_path in files_to_remove:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Removed: {{file_path}}")
        except Exception as e:
            print(f"Failed to remove {{file_path}}: {{e}}")
            
except Exception as e:
    print(f"Update failed: {{e}}")
    
print("Update process finished.")
''')
                
                # Run the cleanup and update script in background
                subprocess.Popen([sys.executable, cleanup_script], 
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                
                messagebox.showinfo("Update", "Update downloaded. The application will restart with the new version.")
                sys.exit()
                
        except Exception as e:
            messagebox.showerror("Update Failed", f"Failed to update: {str(e)}")

    def test_version_comparison(self):
        """Test version comparison logic"""
        test_cases = [
            ("1.1.1", "1.0.5", True),   # 1.1.1 > 1.0.5
            ("2.0.0", "1.9.9", True),   # 2.0.0 > 1.9.9
            ("1.0.5", "1.1.1", False),  # 1.0.5 < 1.1.1
            ("1.0.0", "1.0.0", False),  # 1.0.0 = 1.0.0
            ("1.2", "1.1.9", True),     # 1.2.0 > 1.1.9
            ("v2.1.0", "2.0.5", True),  # v2.1.0 > 2.0.5
        ]
        
        print("Testing version comparison:")
        for latest, current, expected in test_cases:
            result = self.is_newer_version(latest, current)
            status = "✓" if result == expected else "✗"
            print(f"{status} {latest} > {current}: {result} (expected: {expected})")
        
        return all(self.is_newer_version(latest, current) == expected 
                  for latest, current, expected in test_cases)

if __name__ == "__main__":
    updater = Updater()
    # Uncomment the line below to test version comparison
    # updater.test_version_comparison()






