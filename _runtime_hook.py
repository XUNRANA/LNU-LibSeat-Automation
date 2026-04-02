"""
PyInstaller runtime hook.
Runs BEFORE main.py so that `import config` finds the external config.py
sitting next to the .exe, and relative paths (like logs/) resolve correctly.
"""
import sys
import os

if getattr(sys, 'frozen', False):
    exe_dir = os.path.dirname(sys.executable)
    os.chdir(exe_dir)
    sys.path.insert(0, exe_dir)

    # Fix Chinese/emoji display in Windows console
    if sys.platform == 'win32':
        os.system('chcp 65001 >nul 2>&1')
        if sys.stdout is not None:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if sys.stderr is not None:
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
