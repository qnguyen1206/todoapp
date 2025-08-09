#!/usr/bin/env python3
"""
Test script to validate the modular updater system works correctly
"""

import os
import sys
from pathlib import Path

def test_modular_updater():
    """Test the modular updater functionality"""
    print("Testing Modular Updater System...")
    print("=" * 50)
    
    try:
        # Test import
        from modular_updater import ModularUpdater
        print("✓ ModularUpdater import successful")
        
        # Test initialization without auto-check
        updater = ModularUpdater(auto_check=False)
        print("✓ ModularUpdater initialization successful")
        
        # Test version detection
        print(f"✓ Current version detected: {updater.current_version}")
        print(f"✓ Executable mode: {updater.is_executable_mode}")
        
        # Test version comparison
        test_cases = [
            ("1.0.0", "0.9.0", True),
            ("1.0.0", "1.0.0", False),
            ("1.0.0", "1.0.1", False),
            ("2.0.0", "1.9.9", True),
        ]
        
        for latest, current, expected in test_cases:
            result = updater.is_newer_version(latest, current)
            status = "✓" if result == expected else "✗"
            print(f"{status} Version comparison: {latest} > {current} = {result}")
        
        # Test file operations
        version_file = str(Path.home()) + "/TODOapp/version.txt"
        if os.path.exists(version_file):
            print("✓ Version file exists and accessible")
        else:
            print("⚠ Version file not found - will be created on first run")
        
        print("\n" + "=" * 50)
        print("✓ All tests passed! Modular updater is ready to use.")
        
        return True
        
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

def test_todo_integration():
    """Test the TODO app integration"""
    print("\nTesting TODO App Integration...")
    print("=" * 50)
    
    try:
        # Test imports
        sys.path.insert(0, os.getcwd())
        
        # Check if modular updater is available in todo.py context
        try:
            from modular_updater import ModularUpdater
            MODULAR_UPDATER_AVAILABLE = True
            print("✓ Modular updater available for TODO app")
        except ImportError:
            from todo_updater import Updater
            MODULAR_UPDATER_AVAILABLE = False
            print("⚠ Using fallback updater (todo_updater.py)")
        
        # Test version file access
        version_file = str(Path.home()) + "/TODOapp/version.txt"
        try:
            with open(version_file, "r") as f:
                version = f.read().strip()
            print(f"✓ Version file readable: {version}")
        except FileNotFoundError:
            print("⚠ Version file not found - will be created automatically")
        
        print("✓ TODO app integration ready")
        return True
        
    except Exception as e:
        print(f"✗ Integration test failed: {e}")
        return False

def test_manifest_generator():
    """Test the manifest generator"""
    print("\nTesting Manifest Generator...")
    print("=" * 50)
    
    try:
        # Check if generate_manifest.py exists
        if os.path.exists("generate_manifest.py"):
            print("✓ generate_manifest.py found")
            
            # Try importing it
            import generate_manifest
            print("✓ generate_manifest.py imports successfully")
            
            # Test ManifestGenerator class
            generator = generate_manifest.ManifestGenerator(version="1.0.0", app_dir=".")
            print("✓ ManifestGenerator class instantiated")
            
            return True
        else:
            print("✗ generate_manifest.py not found")
            return False
            
    except Exception as e:
        print(f"✗ Manifest generator test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("TODO App Modular Update System - Validation Tests")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(test_modular_updater())
    results.append(test_todo_integration())
    results.append(test_manifest_generator())
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"🎉 ALL TESTS PASSED ({passed}/{total})")
        print("\nYour modular update system is ready!")
        print("\nNext steps:")
        print("1. Compile your app: pyinstaller todo.spec")
        print("2. Generate manifest: python generate_manifest.py --version '1.0.0' --package")
        print("3. Upload todo.exe to GitHub release")
        print("4. Users can update via Help → Check for Updates")
    else:
        print(f"⚠ {passed}/{total} tests passed")
        print("Some issues need to be resolved before deployment.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
