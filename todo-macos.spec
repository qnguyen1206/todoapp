# -*- mode: python ; coding: utf-8 -*-

common_hidden_imports = [
    'PIL',
    'PIL._imagingtk',
    'PIL._tkinter_finder',
    'tkinter',
    'tkinter.filedialog',
    'tkinter.messagebox',
    'tkinter.ttk',
    'tkcalendar',
    'requests',
    'cryptography',
    'cryptography.fernet',
    'mysql.connector',
    'keyring',
    'modular_updater',
    'ai_assistant',
    'mysql_lan_manager',
    'daily_todo_manager',
    'todo_list_manager',
    'calendar_view',
    'cvm_manager',
    'cvm_client',
    'weekly_schedule_view',
    'e2e_crypto',
    'ui_utils',
]

a = Analysis(
    ['todo.py'],
    pathex=[],
    binaries=[],
    datas=[('clipboard.png', '.'), ('version.txt', '.'), ('cvm_defaults.json', '.')],
    hiddenimports=common_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['win32com', 'win32service', 'win32serviceutil'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TODO App',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='TODO App',
)

app = BUNDLE(
    coll,
    name='TODO App.app',
    icon='clipboard.png',
    bundle_identifier='com.kairu.todoapp',
    info_plist={
        'CFBundleDisplayName': 'TODO App',
        'NSHighResolutionCapable': True,
    },
)
