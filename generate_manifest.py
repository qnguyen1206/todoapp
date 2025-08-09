#!/usr/bin/env python3
"""
Manifest Generator for TODO App Modular Updates
This script generates a manifest.json file that describes all the modules,
their versions, and file hashes for modular updates.
"""

import os
import json
import hashlib
import argparse
from pathlib import Path

class ManifestGenerator:
    def __init__(self, version="1.0.0", app_dir="."):
        self.version = version
        self.app_dir = app_dir
        self.modules = {
            # Core application files
            "todo.py": {"type": "core", "required": True},
            "todo.exe": {"type": "core", "required": True},
            
            # Module files
            "ai_assistant.py": {"type": "module", "required": True},
            "mysql_lan_manager.py": {"type": "module", "required": True},
            "daily_todo_manager.py": {"type": "module", "required": True},
            "todo_list_manager.py": {"type": "module", "required": True},
            
            # System files
            "todo_updater.py": {"type": "system", "required": False},
            "modular_updater.py": {"type": "system", "required": False},
            
            # Assets
            "clipboard.png": {"type": "asset", "required": True},
            "version.txt": {"type": "config", "required": True},
            
            # Optional files
            "README.md": {"type": "docs", "required": False},
            "todo.spec": {"type": "build", "required": False},
        }
    
    def calculate_file_hash(self, file_path):
        """Calculate SHA256 hash of a file"""
        try:
            hash_sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except FileNotFoundError:
            return None
    
    def get_file_size(self, file_path):
        """Get file size in bytes"""
        try:
            return os.path.getsize(file_path)
        except FileNotFoundError:
            return 0
    
    def generate_manifest(self):
        """Generate the manifest.json file"""
        manifest = {
            "version": self.version,
            "generated": "2025-08-09T00:00:00Z",  # You can update this
            "modules": {}
        }
        
        print(f"Generating manifest for version {self.version}...")
        print(f"Scanning directory: {os.path.abspath(self.app_dir)}")
        
        for module_name, module_info in self.modules.items():
            file_path = os.path.join(self.app_dir, module_name)
            
            if os.path.exists(file_path):
                file_hash = self.calculate_file_hash(file_path)
                file_size = self.get_file_size(file_path)
                
                if file_hash:
                    manifest["modules"][module_name] = {
                        "version": self.version,
                        "hash": file_hash,
                        "size": file_size,
                        "type": module_info["type"],
                        "required": module_info["required"]
                    }
                    print(f"✓ {module_name} - {file_size} bytes - {file_hash[:16]}...")
                else:
                    print(f"✗ {module_name} - Could not calculate hash")
            else:
                if module_info["required"]:
                    print(f"⚠ {module_name} - Required file missing!")
                else:
                    print(f"- {module_name} - Optional file not found")
        
        return manifest
    
    def save_manifest(self, manifest, output_file="manifest.json"):
        """Save manifest to file"""
        output_path = os.path.join(self.app_dir, output_file)
        
        with open(output_path, "w") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
        
        print(f"\nManifest saved to: {os.path.abspath(output_path)}")
        return output_path
    
    def validate_manifest(self, manifest):
        """Validate the generated manifest"""
        issues = []
        
        # Check for required files
        required_modules = [name for name, info in self.modules.items() if info["required"]]
        for module_name in required_modules:
            if module_name not in manifest["modules"]:
                issues.append(f"Required module missing: {module_name}")
        
        # Check for core application file
        has_core = any(info["type"] == "core" for info in manifest["modules"].values())
        if not has_core:
            issues.append("No core application files found")
        
        return issues
    
    def create_release_package(self, manifest, package_name=None):
        """Create a zip package for GitHub release"""
        import zipfile
        
        if package_name is None:
            package_name = f"todoapp-v{self.version}.zip"
        
        package_path = os.path.join(self.app_dir, package_name)
        
        with zipfile.ZipFile(package_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add manifest
            manifest_path = os.path.join(self.app_dir, "manifest.json")
            if os.path.exists(manifest_path):
                zipf.write(manifest_path, "manifest.json")
            
            # For executable distribution, prioritize the .exe file
            exe_path = os.path.join(self.app_dir, "todo.exe")
            if os.path.exists(exe_path):
                zipf.write(exe_path, "todo.exe")
                print(f"Added to package: todo.exe (main executable)")
            
            # Add essential assets
            essential_files = ["clipboard.png", "version.txt"]
            for file_name in essential_files:
                file_path = os.path.join(self.app_dir, file_name)
                if os.path.exists(file_path):
                    zipf.write(file_path, file_name)
                    print(f"Added to package: {file_name}")
            
            # Only add source files if they exist and user wants them
            # (For executable distribution, usually skip source files)
            source_files = ["todo.py", "ai_assistant.py", "mysql_lan_manager.py", 
                          "daily_todo_manager.py", "todo_list_manager.py", "modular_updater.py"]
            
            print("\nOptional source files (usually not needed for executable distribution):")
            for file_name in source_files:
                file_path = os.path.join(self.app_dir, file_name)
                if os.path.exists(file_path):
                    zipf.write(file_path, file_name)
                    print(f"Added to package: {file_name} (source)")
        
        print(f"\n📦 Release package created: {os.path.abspath(package_path)}")
        print(f"💾 Package size: {os.path.getsize(package_path) / (1024*1024):.1f} MB")
        return package_path

def main():
    parser = argparse.ArgumentParser(description="Generate manifest for TODO App modular updates")
    parser.add_argument("--version", "-v", default="1.0.0", help="Version number for this release")
    parser.add_argument("--dir", "-d", default=".", help="Directory containing the app files")
    parser.add_argument("--output", "-o", default="manifest.json", help="Output manifest filename")
    parser.add_argument("--package", "-p", action="store_true", help="Create release package")
    parser.add_argument("--validate", action="store_true", help="Validate manifest after generation")
    
    args = parser.parse_args()
    
    generator = ManifestGenerator(version=args.version, app_dir=args.dir)
    
    # Generate manifest
    manifest = generator.generate_manifest()
    
    # Validate if requested
    if args.validate:
        issues = generator.validate_manifest(manifest)
        if issues:
            print("\n⚠ Validation Issues:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("\n✓ Manifest validation passed")
    
    # Save manifest
    manifest_path = generator.save_manifest(manifest, args.output)
    
    # Create package if requested
    if args.package:
        package_path = generator.create_release_package(manifest)
        print(f"\nFor GitHub release, upload these files:")
        print(f"  1. {manifest_path}")
        print(f"  2. {package_path}")
        print(f"  3. Individual module files for modular updates")
    
    print(f"\nTotal modules: {len(manifest['modules'])}")
    print("Manifest generation complete!")

if __name__ == "__main__":
    main()
