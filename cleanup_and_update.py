
import os
import time
import sys
import shutil
import zipfile

time.sleep(3)
print("Starting full update process...")

app_dir = r"C:/Users/kylen/TODOapp"
temp_file = r"C:/Users/kylen/TODOapp/update.zip"
cleanup_script = r"C:/Users/kylen/TODOapp/cleanup_and_update.py"

try:
    if temp_file.endswith('.zip'):
        with zipfile.ZipFile(temp_file, 'r') as zip_ref:
            zip_ref.extractall(app_dir)
        print("Full update completed!")
        os.startfile(os.path.join(app_dir, "todo.exe"))
    else:
        shutil.copy2(temp_file, os.path.join(app_dir, "todo.exe"))
        print("Full update completed!")
        os.startfile(os.path.join(app_dir, "todo.exe"))
    
    os.remove(temp_file)
    os.remove(cleanup_script)
except Exception as e:
    print(f"Update failed: {e}")
