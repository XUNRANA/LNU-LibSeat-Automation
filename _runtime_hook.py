"""
PyInstaller runtime hook.
Runs BEFORE main.py so that `import config` finds the external config.py
sitting next to the .exe, and relative paths (like logs/) resolve correctly.
"""
import sys
import os

if getattr(sys, 'frozen', False):
    exe = os.path.realpath(sys.executable)
    if sys.platform == 'darwin':
        # .../发行夹/LNU-LibSeat.app/Contents/MacOS/exe -> 发行夹（.app 同级目录）
        _app_dir = os.path.dirname(os.path.dirname(os.path.dirname(exe)))  # *.app
        base_dir = os.path.dirname(_app_dir) if _app_dir.endswith('.app') else os.path.dirname(exe)
    else:
        base_dir = os.path.dirname(exe)
    os.chdir(base_dir)
    sys.path.insert(0, base_dir)

    # Fix Chinese/emoji display in Windows console
    if sys.platform == 'win32':
        os.system('chcp 65001 >nul 2>&1')
        if sys.stdout is not None:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if sys.stderr is not None:
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
