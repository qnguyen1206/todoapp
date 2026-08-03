import os
import requests
import sys
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
import json
import subprocess
import hashlib
import importlib
import uuid

class ModularUpdater:
    def __init__(self, auto_check=False):
        self.app_dir = self.get_app_dir()
        self.legacy_app_dir = Path.home() / "TODOapp"
        self.version_file = self.resolve_state_file("version.txt")
        self.manifest_file = self.resolve_state_file("manifest.json")
        self.current_version = self.get_current_version()
        self.current_manifest = self.load_local_manifest()
        self.is_executable_mode = getattr(sys, 'frozen', False)  # Detect if running as executable
        self.cleanup_legacy_update_artifacts()
        print(f"Current version: {self.current_version}")
        print(f"Application directory: {self.app_dir}")
        print(f"Running as executable: {self.is_executable_mode}")
        if not self.is_executable_mode:
            print("Source code mode - full modular updates available")
        else:
            print("Executable mode - full updates only")
        
        if auto_check:
            self.check_for_updates()

    def get_app_dir(self):
        """Return the directory where the app is currently running from."""
        if getattr(sys, 'frozen', False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    def resolve_state_file(self, filename):
        """Use app-local state files and migrate from legacy home folder if needed."""
        app_path = self.app_dir / filename
        legacy_path = self.legacy_app_dir / filename

        if app_path.exists():
            return str(app_path)

        if legacy_path.exists():
            try:
                app_path.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(legacy_path, app_path)
                return str(app_path)
            except Exception as e:
                print(f"Could not migrate {filename} to app directory: {e}")
                return str(legacy_path)

        app_path.parent.mkdir(parents=True, exist_ok=True)
        return str(app_path)

    def cleanup_legacy_update_artifacts(self):
        """Remove stale updater artifacts from prior update attempts."""
        artifact_names = ["update.zip", "update.exe", "update_launcher.bat"]
        candidate_dirs = {self.app_dir, self.legacy_app_dir}

        # cleanup_and_update.py is an old runtime artifact from executable updates.
        # Do not remove it from source checkouts where it may be intentionally tracked.
        if self.is_executable_mode:
            artifact_names.append("cleanup_and_update.py")
        else:
            candidate_dirs = {self.legacy_app_dir}

        for base_dir in candidate_dirs:
            for artifact in artifact_names:
                artifact_path = base_dir / artifact
                try:
                    if artifact_path.exists() and artifact_path.is_file():
                        artifact_path.unlink()
                except Exception as e:
                    print(f"Could not remove legacy artifact {artifact_path}: {e}")
    
    def get_current_version(self):
        try:
            with open(self.version_file, "r") as f:
                version = f.read().strip()
                # Clean up version string
                parts = []
                for part in version.split('.'):
                    if part.isalpha():
                        parts.append(part)
                    else:
                        num = ''.join(c for c in part if c.isdigit()) or '0'
                        parts.append(num)
                return '.'.join(parts[:3])
        except FileNotFoundError:
            os.makedirs(os.path.dirname(self.version_file), exist_ok=True)
            with open(self.version_file, "w") as f:
                f.write("0.0.0")
            return "0.0.0"
    
    def load_local_manifest(self):
        """Load local manifest with file hashes and versions"""
        try:
            with open(self.manifest_file, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            # Create default manifest
            default_manifest = {
                "version": self.current_version,
                "modules": {
                    "todo.py": {"version": self.current_version, "hash": "", "type": "core"},
                    "ai_assistant.py": {"version": self.current_version, "hash": "", "type": "module"},
                    "mysql_lan_manager.py": {"version": self.current_version, "hash": "", "type": "module"},
                    "daily_todo_manager.py": {"version": self.current_version, "hash": "", "type": "module"},
                    "todo_list_manager.py": {"version": self.current_version, "hash": "", "type": "module"},
                    "cvm_client.py": {"version": self.current_version, "hash": "", "type": "module"},
                    "cvm_manager.py": {"version": self.current_version, "hash": "", "type": "module"},
                    "modular_updater.py": {"version": self.current_version, "hash": "", "type": "system"},
                    "clipboard.png": {"version": self.current_version, "hash": "", "type": "asset"},
                    "version.txt": {"version": self.current_version, "hash": "", "type": "config"},
                    "cvm_config.json": {"version": self.current_version, "hash": "", "type": "config"}
                }
            }
            self.save_local_manifest(default_manifest)
            return default_manifest
    
    def save_local_manifest(self, manifest):
        """Save manifest to local file"""
        with open(self.manifest_file, "w") as f:
            json.dump(manifest, f, indent=2)
    
    def calculate_file_hash(self, file_path):
        """Calculate SHA256 hash of a file"""
        try:
            hash_sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except FileNotFoundError:
            return ""
    
    def check_for_updates(self):
        try:
            github_username = "Kairu1206"
            repo_name = "todoapp"
            
            # Check for latest release with timeout
            api_url = f"https://api.github.com/repos/{github_username}/{repo_name}/releases/latest"
            response = requests.get(api_url, timeout=5)  # Add 5s timeout
            
            if response.status_code == 200:
                latest_release = json.loads(response.text)
                latest_version = latest_release["tag_name"].lstrip("v")
                
                if self.is_newer_version(latest_version, self.current_version):
                    # In executable mode, look for zip file containing executable
                    if self.is_executable_mode:
                        zip_asset = None
                        exe_asset = None
                        
                        # Look for zip files first (preferred for GitHub releases)
                        for asset in latest_release["assets"]:
                            if asset["name"].endswith(".zip"):
                                zip_asset = asset
                                break
                            elif asset["name"].endswith(".exe"):
                                exe_asset = asset
                        
                        if zip_asset:
                            self.prompt_full_update(latest_version, zip_asset["browser_download_url"])
                        elif exe_asset:
                            self.prompt_full_update(latest_version, exe_asset["browser_download_url"])
                        else:
                            print("No executable or zip package found in release for executable mode")
                    else:
                        # Source code mode - check for modular updates
                        manifest_url = None
                        download_assets = {}
                        
                        for asset in latest_release["assets"]:
                            if asset["name"] == "manifest.json":
                                manifest_url = asset["browser_download_url"]
                            else:
                                download_assets[asset["name"]] = asset["browser_download_url"]
                        
                        if manifest_url:
                            modular_updates = self.check_modular_updates(manifest_url, download_assets, latest_version)
                            if not modular_updates:
                                # No modular updates, check for full update
                                zip_asset = None
                                for asset in latest_release["assets"]:
                                    if asset["name"].endswith(".zip"):
                                        zip_asset = asset
                                        break
                                if zip_asset:
                                    self.prompt_full_update(latest_version, zip_asset["browser_download_url"])
                        else:
                            # Fallback to full update if no manifest
                            self.prompt_full_update(latest_version, latest_release["assets"][0]["browser_download_url"])
                else:
                    print("No updates available - you have the latest version")
        except Exception as e:
            print(f"Update check failed: {e}")
    
    def check_modular_updates(self, manifest_url, download_assets, new_version):
        """Check which modules need updating based on manifest"""
        # Skip modular updates if running as executable (source code not available)
        if self.is_executable_mode:
            print("Executable mode: Skipping modular updates, only full updates available")
            return False
            
        try:
            # Download remote manifest
            response = requests.get(manifest_url)
            if response.status_code != 200:
                return False
            
            remote_manifest = json.loads(response.text)
            updates_needed = []
            
            # Compare local and remote manifests
            for module_name, remote_info in remote_manifest["modules"].items():
                local_info = self.current_manifest["modules"].get(module_name, {})
                
                # Check if module needs updating
                if (remote_info["hash"] != local_info.get("hash", "") or 
                    self.is_newer_version(remote_info["version"], local_info.get("version", "0.0.0"))):
                    
                    if module_name in download_assets:
                        updates_needed.append({
                            "name": module_name,
                            "url": download_assets[module_name],
                            "type": remote_info["type"],
                            "version": remote_info["version"],
                            "hash": remote_info["hash"]
                        })
            
            if updates_needed:
                self.prompt_modular_update(updates_needed, remote_manifest, new_version)
                return True
            else:
                print("No modular updates needed - all modules are up to date")
                return False
        
        except Exception as e:
            print(f"Modular update check failed: {e}")
            return False
    
    def prompt_modular_update(self, updates_needed, remote_manifest, new_version):
        """Show update dialog with details of what will be updated"""
        root = tk.Tk()
        root.withdraw()
        
        # Create detailed update message
        core_updates = [u for u in updates_needed if u["type"] == "core"]
        module_updates = [u for u in updates_needed if u["type"] == "module"]
        asset_updates = [u for u in updates_needed if u["type"] == "asset"]
        
        message_parts = [f"Update to version {new_version} available!\n"]
        
        if core_updates:
            message_parts.append("Core application updates:")
            for update in core_updates:
                message_parts.append(f"  • {update['name']} (v{update['version']})")
            message_parts.append("")
        
        if module_updates:
            message_parts.append("Module updates:")
            for update in module_updates:
                message_parts.append(f"  • {update['name']} (v{update['version']})")
            message_parts.append("")
        
        if asset_updates:
            message_parts.append("Asset updates:")
            for update in asset_updates:
                message_parts.append(f"  • {update['name']}")
            message_parts.append("")
        
        total_size = len(updates_needed)
        message_parts.append(f"Total: {total_size} file(s) to update")
        message_parts.append("\nUpdate now?")
        
        message = "\n".join(message_parts)
        
        if messagebox.askyesno("Modular Update Available", message):
            self.download_and_apply_updates(updates_needed, remote_manifest, new_version)
        
        root.destroy()
    
    def download_and_apply_updates(self, updates_needed, remote_manifest, new_version):
        """Download and apply modular updates"""
        try:
            download_path = self.app_dir / "updates"
            download_path.mkdir(parents=True, exist_ok=True)
            
            # Show progress dialog
            progress_window = self.create_progress_window()
            
            downloaded_files = []
            total_updates = len(updates_needed)
            
            for i, update in enumerate(updates_needed):
                # Update progress
                progress = int((i / total_updates) * 100)
                self.update_progress(progress_window, f"Downloading {update['name']}...", progress)
                
                # Download file
                response = requests.get(update["url"], stream=True)
                if response.status_code == 200:
                    temp_file = download_path / update["name"]
                    temp_file.parent.mkdir(parents=True, exist_ok=True)
                    
                    with open(temp_file, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    # Verify hash
                    downloaded_hash = self.calculate_file_hash(temp_file)
                    if downloaded_hash == update["hash"]:
                        downloaded_files.append({
                            "temp_path": str(temp_file),
                            "target_name": update["name"],
                            "type": update["type"]
                        })
                    else:
                        print(f"Hash mismatch for {update['name']}")
                        self.cleanup_temp_files([str(temp_file)])
                        messagebox.showerror("Update Failed", f"File verification failed for {update['name']}")
                        return
            
            # Apply updates
            self.update_progress(progress_window, "Applying updates...", 90)
            needs_restart = self.apply_downloaded_updates(downloaded_files)
            
            # Update manifest and version
            self.current_manifest = remote_manifest
            self.save_local_manifest(remote_manifest)
            
            with open(self.version_file, "w") as f:
                f.write(new_version)
            
            # Cleanup
            self.cleanup_temp_files([f["temp_path"] for f in downloaded_files])
            
            # Close progress and show completion
            progress_window.destroy()
            
            if needs_restart:
                if messagebox.askyesno("Update Complete", 
                                     "Update completed successfully!\n\nThe application needs to restart to apply core updates. Restart now?"):
                    self.restart_application()
            else:
                # Try hot reloading modules
                self.hot_reload_modules(downloaded_files)
                messagebox.showinfo("Update Complete", "Update completed successfully!\n\nModules have been reloaded.")
        
        except Exception as e:
            messagebox.showerror("Update Failed", f"Failed to apply updates: {str(e)}")
    
    def create_progress_window(self):
        """Create a progress window for updates"""
        progress_window = tk.Toplevel()
        progress_window.title("Updating TODO App")
        progress_window.geometry("400x150")
        progress_window.resizable(False, False)
        
        # Center the window
        progress_window.transient()
        progress_window.grab_set()
        
        # Progress label
        progress_label = tk.Label(progress_window, text="Preparing update...", font=('Arial', 10))
        progress_label.pack(pady=20)
        
        # Progress bar
        from tkinter import ttk
        progress_bar = ttk.Progressbar(progress_window, length=300, mode='determinate')
        progress_bar.pack(pady=10)
        
        # Store references
        progress_window.label = progress_label
        progress_window.bar = progress_bar
        
        progress_window.update()
        return progress_window
    
    def update_progress(self, window, text, progress):
        """Update progress window"""
        window.label.config(text=text)
        window.bar['value'] = progress
        window.update()
    
    def apply_downloaded_updates(self, downloaded_files):
        """Apply downloaded updates to the application"""
        needs_restart = False
        current_dir = str(self.app_dir)
        
        for file_info in downloaded_files:
            target_path = os.path.join(current_dir, file_info["target_name"])
            
            # Check if this is a core file that requires restart
            if file_info["type"] == "core" or file_info["target_name"].endswith(".exe"):
                needs_restart = True
            
            # Copy file to target location
            try:
                if os.path.exists(target_path):
                    # Backup original file
                    backup_path = target_path + ".backup"
                    if os.path.exists(backup_path):
                        os.remove(backup_path)
                    os.rename(target_path, backup_path)
                
                # Copy new file
                import shutil
                shutil.copy2(file_info["temp_path"], target_path)
                print(f"Updated: {file_info['target_name']}")
                
            except Exception as e:
                print(f"Failed to update {file_info['target_name']}: {e}")
                # Restore backup if copy failed
                backup_path = target_path + ".backup"
                if os.path.exists(backup_path):
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    os.rename(backup_path, target_path)
        
        return needs_restart
    
    def hot_reload_modules(self, downloaded_files):
        """Attempt to hot reload Python modules without restart"""
        try:
            for file_info in downloaded_files:
                if file_info["target_name"].endswith(".py") and file_info["type"] == "module":
                    module_name = file_info["target_name"][:-3]  # Remove .py extension
                    
                    try:
                        # Try to reload the module
                        if module_name in sys.modules:
                            importlib.reload(sys.modules[module_name])
                            print(f"Hot reloaded: {module_name}")
                    except Exception as e:
                        print(f"Could not hot reload {module_name}: {e}")
        except Exception as e:
            print(f"Hot reload failed: {e}")
    
    def cleanup_temp_files(self, file_paths):
        """Clean up temporary downloaded files"""
        for file_path in file_paths:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"Could not remove temp file {file_path}: {e}")
    
    def restart_application(self):
        """Restart the application"""
        try:
            current_exe = sys.executable if not getattr(sys, 'frozen', False) else sys.argv[0]
            subprocess.Popen([current_exe] + sys.argv[1:])
            sys.exit()
        except Exception as e:
            print(f"Could not restart application: {e}")
    
    def prompt_full_update(self, new_version, download_url):
        """Fallback to full update if modular update not available"""
        root = tk.Tk()
        root.withdraw()
        
        # In executable mode, provide a more user-friendly message
        if self.is_executable_mode:
            message = (f"TODO App version {new_version} is available!\n\n"
                      f"Current version: {self.current_version}\n"
                      f"New version: {new_version}\n\n"
                      f"The update will download and install automatically.\n"
                      f"Your data and settings will be preserved.\n\n"
                      f"Update now?")
        else:
            message = f"Version {new_version} is available (full update required). Update now?"
        
        if messagebox.askyesno("Update Available", message):
            self.download_and_install_full(download_url, new_version)
        
        root.destroy()
    
    def download_and_install_full(self, url, new_version):
        """Full update fallback (original method)"""
        try:
            response = requests.get(url, stream=True)
            if response.status_code == 200:
                is_zip = url.lower().endswith('.zip')
                work_dir = self.app_dir / ".update_tmp" / uuid.uuid4().hex
                work_dir.mkdir(parents=True, exist_ok=True)
                temp_file = work_dir / ("package.zip" if is_zip else "package.exe")
                
                with open(temp_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                if self.is_executable_mode:
                    self.launch_windows_inplace_update_worker(temp_file, work_dir, new_version)
                else:
                    self.apply_full_update_source_mode(temp_file, is_zip, new_version)
                
                messagebox.showinfo("Update", "Update downloaded. The application will restart.")
                sys.exit()
                
        except Exception as e:
            messagebox.showerror("Update Failed", f"Failed to update: {str(e)}")

    def launch_windows_inplace_update_worker(self, package_path, work_dir, new_version):
        """Run update worker in a separate PowerShell process so the current exe can exit."""
        ps_script_path = work_dir / "apply_update.ps1"
        app_dir_str = str(self.app_dir)
        package_str = str(package_path)
        work_dir_str = str(work_dir)
        version_file_str = str(Path(self.version_file))
        main_exe_str = str(self.app_dir / "todo.exe")
        legacy_dir_str = str(self.legacy_app_dir)
        current_pid = os.getpid()

        script_content = f'''$ErrorActionPreference = "Stop"
$AppDir = "{app_dir_str}"
$PackagePath = "{package_str}"
$WorkDir = "{work_dir_str}"
$VersionFile = "{version_file_str}"
$MainExe = "{main_exe_str}"
$LegacyDir = "{legacy_dir_str}"
$ParentPid = {current_pid}

function Remove-IfExists([string]$PathValue) {{
    if (Test-Path -LiteralPath $PathValue) {{
        Remove-Item -LiteralPath $PathValue -Force -Recurse -ErrorAction SilentlyContinue
    }}
}}

function Copy-Payload([string]$SourceRoot, [string]$TargetRoot) {{
    $protectedNames = @("todo.txt","dailytask.txt","daily_date.txt","storage_pref.txt","time_format_pref.txt","mysql_config.json","cvm_config.json","ai_config.json","uploads")
    Get-ChildItem -LiteralPath $SourceRoot -Force | ForEach-Object {{
        if ($protectedNames -contains $_.Name) {{ return }}
        $dest = Join-Path $TargetRoot $_.Name
        if ($_.PSIsContainer) {{
            Copy-Item -LiteralPath $_.FullName -Destination $dest -Recurse -Force
        }} else {{
            Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
        }}
    }}
}}

try {{
    Wait-Process -Id $ParentPid -ErrorAction SilentlyContinue

    if ($PackagePath.ToLower().EndsWith(".zip")) {{
        $ExtractDir = Join-Path $WorkDir "extracted"
        New-Item -ItemType Directory -Path $ExtractDir -Force | Out-Null
        Expand-Archive -LiteralPath $PackagePath -DestinationPath $ExtractDir -Force

        $PayloadDir = $ExtractDir
        $Children = Get-ChildItem -LiteralPath $ExtractDir -Force
        if ($Children.Count -eq 1 -and $Children[0].PSIsContainer) {{
            $PayloadDir = $Children[0].FullName
        }}

        Copy-Payload -SourceRoot $PayloadDir -TargetRoot $AppDir
    }} else {{
        Copy-Item -LiteralPath $PackagePath -Destination $MainExe -Force
    }}

    Set-Content -LiteralPath $VersionFile -Value "{new_version}" -NoNewline

    Remove-IfExists (Join-Path $AppDir "update.zip")
    Remove-IfExists (Join-Path $AppDir "update.exe")
    Remove-IfExists (Join-Path $AppDir "cleanup_and_update.py")
    Remove-IfExists (Join-Path $LegacyDir "update.zip")
    Remove-IfExists (Join-Path $LegacyDir "update.exe")
    Remove-IfExists (Join-Path $LegacyDir "cleanup_and_update.py")

    if (Test-Path -LiteralPath $MainExe) {{
        Start-Process -FilePath $MainExe -WorkingDirectory $AppDir
    }}
}} catch {{
    "Update failed: $($_.Exception.Message)" | Out-File -FilePath (Join-Path $WorkDir "update_error.log") -Encoding utf8
}}

$cleanupCmd = "ping 127.0.0.1 -n 3 > nul & rmdir /s /q `"$WorkDir`""
Start-Process -FilePath "cmd.exe" -ArgumentList "/c $cleanupCmd" -WindowStyle Hidden
'''

        with open(ps_script_path, "w", encoding="utf-8") as f:
            f.write(script_content)

        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps_script_path)
            ],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )

    def apply_full_update_source_mode(self, package_path, is_zip, new_version):
        """Apply full update in source mode directly from Python."""
        import shutil
        import zipfile

        if is_zip:
            with zipfile.ZipFile(package_path, 'r') as zip_ref:
                zip_ref.extractall(str(self.app_dir))
        else:
            shutil.copy2(str(package_path), str(self.app_dir / "todo.exe"))

        with open(self.version_file, "w") as f:
            f.write(new_version)

        self.cleanup_temp_files([str(package_path)])
    
    def is_newer_version(self, latest, current):
        """Compare version strings properly"""
        try:
            latest = latest.strip().lstrip('v')
            current = current.strip().lstrip('v')
            
            if not latest or not current:
                return False
            
            latest_parts = latest.split(".")
            current_parts = current.split(".")
            
            def parse_version_part(part):
                numeric_part = ""
                for char in part:
                    if char.isdigit():
                        numeric_part += char
                    else:
                        break
                return int(numeric_part) if numeric_part else 0
            
            latest_nums = [parse_version_part(part) for part in latest_parts]
            current_nums = [parse_version_part(part) for part in current_parts]
            
            max_length = max(len(latest_nums), len(current_nums))
            latest_nums.extend([0] * (max_length - len(latest_nums)))
            current_nums.extend([0] * (max_length - len(current_nums)))
            
            for i in range(max_length):
                if latest_nums[i] > current_nums[i]:
                    return True
                elif latest_nums[i] < current_nums[i]:
                    return False
            
            return False
            
        except Exception as e:
            print(f"Version comparison error: {e}")
            return False

# For backward compatibility, keep the old Updater class as an alias
Updater = ModularUpdater

if __name__ == "__main__":
    updater = ModularUpdater(auto_check=True)
