import sys
import unittest
from pathlib import Path
from unittest import mock

from modular_updater import ModularUpdater


ROOT = Path(__file__).resolve().parents[1]


class DesktopPackagingTests(unittest.TestCase):
    def test_specs_bundle_public_defaults_not_private_account_config(self):
        package_files = (
            "todo.spec",
            "todo-macos.spec",
            "todo-linux.spec",
            "generate_manifest.py",
        )
        for spec_name in package_files:
            source = (ROOT / spec_name).read_text(encoding="utf-8")
            self.assertIn("cvm_defaults.json", source)
            self.assertNotIn('"cvm_config.json": {"type": "config"', source)
            self.assertNotIn("('cvm_config.json', '.')", source)

    def test_release_workflow_builds_all_supported_desktop_packages(self):
        workflow = (ROOT / ".github/workflows/build-desktop.yml").read_text(encoding="utf-8")
        for package in (
            "TODO-App-Windows-x64",
            "TODO-App-macOS-Intel",
            "TODO-App-macOS-Apple-Silicon",
            "TODO-App-Linux-x64",
        ):
            self.assertIn(package, workflow)
        self.assertIn("branches: [master]", workflow)
        self.assertIn("release_tag:", workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", workflow)

    def test_updater_selects_only_the_current_platform_asset(self):
        updater = ModularUpdater.__new__(ModularUpdater)
        assets = [
            {"name": "TODO-App-Windows-x64.zip"},
            {"name": "TODO-App-macOS-Intel.zip"},
            {"name": "TODO-App-macOS-Apple-Silicon.zip"},
            {"name": "TODO-App-Linux-x64.tar.gz"},
        ]

        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch("modular_updater.platform.machine", return_value="arm64"):
            selected = updater.select_platform_asset(assets)
            self.assertEqual(selected["name"], "TODO-App-macOS-Apple-Silicon.zip")

        with mock.patch.object(sys, "platform", "win32"):
            selected = updater.select_platform_asset(assets)
            self.assertEqual(selected["name"], "TODO-App-Windows-x64.zip")


if __name__ == "__main__":
    unittest.main()
