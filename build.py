"""
LNU-LibSeat-Automation Build Script
====================================
Packages the project into a standalone folder that runs without Python.

How it works:
    1. Auto-creates a clean temporary venv (isolates from Anaconda / torch / etc.)
    2. Installs ONLY the required packages (selenium, ddddocr, pyinstaller)
    3. Runs PyInstaller inside the clean venv
    4. Cleans up the venv after build

This guarantees a fast, clean build regardless of what is installed globally.

Usage:
    python build.py

Output:
    dist/LNU-LibSeat/
        LNU-LibSeat.exe   <- Double-click to run (GUI)
        logs/              <- Log output (auto-created)
"""
import subprocess
import sys
import shutil
import os
import venv

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "LNU-LibSeat"
APP_VERSION = "v2.3.0"  # 每次发布新版本请修改此处
DIST_NAME = f"{APP_NAME}-{APP_VERSION}"
DIST_DIR = os.path.join(ROOT, "dist", DIST_NAME)
VENV_DIR = os.path.join(ROOT, ".build_venv")

# Only these packages (and their dependencies) go into the exe
BUILD_DEPS = ["pyinstaller", "selenium", "ddddocr", "customtkinter"]


def _venv_python():
    """Return the python executable path inside the build venv."""
    if sys.platform == "win32":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python")


def _create_clean_venv():
    """Create a fresh venv with only the required packages."""
    if os.path.exists(VENV_DIR):
        print("[*] Removing old build venv...")
        shutil.rmtree(VENV_DIR)

    print("[*] Creating clean build venv...")
    venv.create(VENV_DIR, with_pip=True)

    py = _venv_python()
    if not os.path.isfile(py):
        sys.exit(f"[ERROR] venv python not found: {py}")

    print("[*] Installing build dependencies (selenium, ddddocr, pyinstaller)...")
    subprocess.check_call(
        [py, "-m", "pip", "install", "--upgrade", "pip"],
        stdout=subprocess.DEVNULL,
    )
    subprocess.check_call(
        [py, "-m", "pip", "install"] + BUILD_DEPS,
    )
    print("[OK] Build venv ready.\n")


def build():
    # --- Step 1: Clean build venv ---
    _create_clean_venv()
    py = _venv_python()

    # --- Step 2: Run PyInstaller in clean venv ---
    cmd = [
        py, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--name", APP_NAME,  # 保持 exe 名称为 LNU-LibSeat.exe，但文件夹会有版本号
        "--distpath", os.path.join(ROOT, "dist"),
        "--windowed",  # GUI 模式，无黑框

        # Add the custom icon for the taskbar and executable
        "--icon", os.path.join(ROOT, "logo.ico"),
        "--add-data", f"{os.path.join(ROOT, 'logo.ico')};.",
        "--add-data", f"{os.path.join(ROOT, 'logo.png')};.",

        # Runtime hook: set cwd and sys.path to exe dir before any imports
        "--runtime-hook", os.path.join(ROOT, "_runtime_hook.py"),

        # Bundle these packages with their native libs / data files
        "--collect-all", "ddddocr",
        "--collect-all", "onnxruntime",
        "--collect-all", "selenium",
        "--collect-all", "customtkinter",

        # Do NOT bundle config.py — users edit the external copy
        "--exclude-module", "config",

        # Entry point: GUI
        os.path.join(ROOT, "gui.py"),
    ]

    print("=" * 55)
    print("  Building LNU-LibSeat-Automation ...")
    print("=" * 55)
    subprocess.check_call(cmd)

    # --- Step 3: Clean up build venv ---
    print("[*] Cleaning up build venv...")
    shutil.rmtree(VENV_DIR, ignore_errors=True)

    # --- Step 4: Rename output folder ---
    original_dist_folder = os.path.join(ROOT, "dist", APP_NAME)
    if os.path.exists(original_dist_folder) and APP_NAME != DIST_NAME:
        if os.path.exists(DIST_DIR):
            shutil.rmtree(DIST_DIR)
        os.rename(original_dist_folder, DIST_DIR)

    # --- Step 5: Post-build — set up distribution folder ---

    # Copy logo.png to exe directory so GUI can find it directly
    src_logo = os.path.join(ROOT, "logo.png")
    if os.path.exists(src_logo):
        shutil.copy2(src_logo, os.path.join(DIST_DIR, "logo.png"))
        print("[OK] logo.png copied to distribution folder")

    # Create logs directory
    os.makedirs(os.path.join(DIST_DIR, "logs"), exist_ok=True)
    print("[OK] logs/ directory created")

    # Write a clean config template (NEVER ship personal data)
    clean_config = '''\
# ===================================================================
# LNU-LibSeat-Automation 配置文件 (由 GUI 自动保存)
# ===================================================================

USERS = {
    "你的学号": {
        "password": "你的密码",
        "time": {"start": "9:00", "end": "15:00"}
    },
}

TARGET_CAMPUS = "崇山校区图书馆"
TARGET_ROOM = "三楼智慧研修空间"
PREFER_SEATS = ["001", "002", "003", "004"]

WAIT_FOR_0630 = True
HEADLESS = True
BROWSER = "edge"
DRIVER_PATH = ""
WEBDRIVER_CACHE = ""

RECEIVER_EMAIL = ""
SMTP_USER = ""
SMTP_PASS = ""

LOG_LEVEL = "INFO"
LOG_DIR = "logs"
'''
    config_path = os.path.join(DIST_DIR, "config.py")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(clean_config)
    print("[OK] Clean config.py template written (no personal data)")

    # --- Step 6: Create Zip ---
    print(f"[*] Packaging {DIST_NAME}.zip ...")
    shutil.make_archive(
        base_name=os.path.join(ROOT, "dist", DIST_NAME),
        format='zip',
        root_dir=os.path.join(ROOT, "dist"),
        base_dir=DIST_NAME
    )
    print(f"[OK] {DIST_NAME}.zip created successfully")

    print()
    print("=" * 55)
    print(f"  Build complete!")
    print(f"  Output Folder: dist/{DIST_NAME}/")
    print(f"  Output Zip: dist/{DIST_NAME}.zip")
    print()
    print("  How to use:")
    print(f"  1. Double-click  dist/{DIST_NAME}/{APP_NAME}.exe")
    print("  2. Fill in the form and click Start")
    print("=" * 55)


if __name__ == "__main__":
    build()
