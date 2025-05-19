
import os
import time
import sys
from pathlib import Path

# Wait a moment for the original process to exit
time.sleep(2)

# Files to clean up
files_to_remove = [
    r"C:/Users/kylen/TODOapp/update.zip",
    r"C:/Users/kylen/TODOapp/cleanup.py"
]

# Remove each file
for file_path in files_to_remove:
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Removed: {file_path}")
    except Exception as e:
        print(f"Failed to remove {file_path}: {e}")
