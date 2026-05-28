"""
LNU-LibSeat-Automation macOS 构建脚本
=====================================
把项目打包成可双击的 macOS ``.app``，并装入一个发行夹后用 ``ditto`` 压成 zip。

⚠️ PyInstaller 不能跨平台编译：本脚本**必须在 macOS 上运行**（本地 Apple
   Silicon Mac，或 GitHub Actions 的 macos-14 runner）。在 Windows 上无法产出 .app。

工作流程：
    1. 创建干净的临时 venv（隔离 Anaconda / torch 等）
    2. 只安装运行所需的包
    3. 用 sips + iconutil 从 logo.png 生成 logo.icns
    4. 在干净 venv 内运行 PyInstaller，产出 dist/LNU-LibSeat.app
    5. 组装发行夹（.app + 外置可编辑 config.py + info/ + logs/ + 解除限制脚本 + 说明）
    6. 用 ditto 压成 zip（保留 .app 内的符号链接与签名）
    7. 清理临时 venv

用法（在 Mac 上）：
    python3 build_mac.py

产物：
    dist/LNU-LibSeat-v5.0.0-macOS-arm64/        <- 发行夹
    dist/LNU-LibSeat-v5.0.0-macOS-arm64.zip      <- 分发给用户的压缩包
"""
import os
import platform
import shutil
import subprocess
import sys
import venv

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "LNU-LibSeat"
APP_VERSION = "v5.0.0"  # 每次发布新版本请修改此处
ARCH = platform.machine() or "arm64"  # arm64 (Apple Silicon)
DIST_NAME = f"{APP_NAME}-{APP_VERSION}-macOS-{ARCH}"
DIST_DIR = os.path.join(ROOT, "dist", DIST_NAME)
VENV_DIR = os.path.join(ROOT, ".build_venv_mac")
BUNDLE_ID = "com.xunrana.lnulibseat"

# 只把这些包（及其依赖）打进 .app
BUILD_DEPS = [
    "pyinstaller", "PySide6", "selenium", "ddddocr",
    "opencv-python", "numpy", "onnxruntime", "Pillow",
    "requests", "webdriver-manager", "mss",
]


def _venv_python():
    return os.path.join(VENV_DIR, "bin", "python")


def _create_clean_venv():
    if os.path.exists(VENV_DIR):
        print("[*] 移除旧的 build venv...")
        shutil.rmtree(VENV_DIR)

    print("[*] 创建干净的 build venv...")
    venv.create(VENV_DIR, with_pip=True)

    py = _venv_python()
    if not os.path.isfile(py):
        sys.exit(f"[ERROR] venv python 未找到: {py}")

    print("[*] 安装构建依赖（arm64 wheel）...")
    subprocess.check_call([py, "-m", "pip", "install", "--upgrade", "pip"],
                          stdout=subprocess.DEVNULL)
    subprocess.check_call([py, "-m", "pip", "install"] + BUILD_DEPS)
    print("[OK] build venv 就绪。\n")


def _make_icns():
    """用 macOS 自带 sips + iconutil 从 logo.png 生成 logo.icns；失败则返回 None。"""
    png = os.path.join(ROOT, "logo.png")
    if not os.path.exists(png):
        print("[WARN] 未找到 logo.png，将不带自定义图标。")
        return None

    iconset = os.path.join(ROOT, "logo.iconset")
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(iconset)
    icns = os.path.join(ROOT, "logo.icns")
    try:
        for s in (16, 32, 64, 128, 256, 512):
            subprocess.check_call(
                ["sips", "-z", str(s), str(s), png,
                 "--out", os.path.join(iconset, f"icon_{s}x{s}.png")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.check_call(
                ["sips", "-z", str(s * 2), str(s * 2), png,
                 "--out", os.path.join(iconset, f"icon_{s}x{s}@2x.png")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.check_call(["iconutil", "-c", "icns", iconset, "-o", icns])
        print("[OK] logo.icns 生成成功。")
        return icns
    except Exception as e:
        print(f"[WARN] icns 生成失败，将不带自定义图标: {e}")
        return None
    finally:
        shutil.rmtree(iconset, ignore_errors=True)


# 干净的配置模板（绝不打包个人数据；macOS 默认浏览器 = chrome）
CLEAN_CONFIG = '''\
# ===================================================================
# LNU-LibSeat-Automation 配置文件 (由 GUI 自动保存)
# ===================================================================

USERS = {
    "": {
        "password": "",
        "time": {"start": "", "end": ""}
    },
}

TARGET_CAMPUS = "崇山校区图书馆"
TARGET_ROOM = "三楼智慧研修空间"
PREFER_SEATS = []

WAIT_FOR_0630 = False
MAX_ACCOUNTS = 2

BROWSER = "chrome"
DRIVER_PATH = ""
WEBDRIVER_CACHE = ""

RECEIVER_EMAIL = ""
SMTP_USER = ""
SMTP_PASS = ""

LOG_LEVEL = "INFO"
LOG_DIR = "logs"
'''

# 一键解除 Gatekeeper 限制脚本（未签名 .app 首次需要）
UNLOCK_COMMAND = '''\
#!/bin/bash
# 解除 macOS 对未签名应用的隔离限制，然后启动应用。
cd "$(dirname "$0")"
echo "正在解除安全限制（可能需要几秒）..."
xattr -cr "LNU-LibSeat.app" 2>/dev/null
chmod +x "LNU-LibSeat.app/Contents/MacOS/LNU-LibSeat" 2>/dev/null
echo "完成！正在启动 LNU-LibSeat..."
open "LNU-LibSeat.app"
'''

USAGE_TXT = '''\
LNU-LibSeat 图书馆智能抢座系统 · macOS 使用说明
================================================

【首次运行】
1. 把本文件夹整个解压到任意位置（例如「下载」或「桌面」）。
2. 右键点击「首次运行请先双击我.command」→ 选择「打开」→ 再点一次「打开」。
   （因为应用未做苹果付费签名，必须用右键打开一次以解除安全限制；
     之后即可直接双击 LNU-LibSeat.app 启动。）
3. 如果第 2 步提示「无法打开」，请到 系统设置 ▸ 隐私与安全性 ▸ 底部「仍要打开」。

【浏览器要求】
- 默认使用 Chrome，请先安装 Google Chrome（推荐，支持双账号并行）。
- 如果想用 Safari：在应用内「浏览器」选择 Safari，并先开启：
  Safari ▸ 设置 ▸ 高级 ▸ 勾选「在菜单栏显示开发菜单」→ 开发 ▸ 允许远程自动化。
  （注意：Safari 只支持单账号，不支持双账号并行。）

【数据位置】
- config.py（你的配置）、logs/（运行日志）都在本文件夹内，与 .app 同级，可直接查看/编辑。

【注意】
- 抢座等待期间请保持电脑开机；应用会自动防止系统休眠。
- 屏幕录制功能在 macOS 上可能不可用（不影响抢座）。
'''


def build():
    if sys.platform != "darwin":
        sys.exit("[ERROR] build_mac.py 只能在 macOS 上运行。Windows 请用 build.py，"
                 "或通过 GitHub Actions 的 macos runner 构建。")

    # --- Step 1: venv ---
    _create_clean_venv()
    py = _venv_python()

    # --- Step 2: icns ---
    icns = _make_icns()

    # --- Step 3: PyInstaller ---
    sep = os.pathsep  # macOS = ":"
    cmd = [
        py, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",                       # 生成 .app（GUI，无终端窗口）
        "--name", APP_NAME,
        "--distpath", os.path.join(ROOT, "dist"),
        "--osx-bundle-identifier", BUNDLE_ID,

        # 运行时 hook：在任何 import 前把 cwd / sys.path 指向 .app 同级目录
        "--runtime-hook", os.path.join(ROOT, "_runtime_hook.py"),

        # 随包资源
        "--add-data", f"{os.path.join(ROOT, 'logo.png')}{sep}.",
        "--add-data", f"{os.path.join(ROOT, 'logo1.png')}{sep}.",
        "--add-data", f"{os.path.join(ROOT, 'logo.ico')}{sep}.",
        # 验证码 ONNX 模型 -> _MEIPASS/core/checkpoints（由 core.paths.resource_root 定位）
        "--add-data", f"{os.path.join(ROOT, 'core', 'checkpoints')}{sep}core/checkpoints",

        # 带原生库 / 数据文件的包
        "--collect-all", "ddddocr",
        "--collect-all", "onnxruntime",
        "--collect-all", "selenium",
        "--collect-all", "PySide6",
        "--collect-all", "cv2",
        "--collect-all", "numpy",

        # 不打包 config.py（用户编辑外置副本）
        "--exclude-module", "config",
        # 排除运行时用不到的训练 / 推理重型依赖
        "--exclude-module", "torch",
        "--exclude-module", "torchvision",
        "--exclude-module", "timm",
        "--exclude-module", "scipy",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pandas",
        "--exclude-module", "ultralytics",
        "--exclude-module", "tensorboard",
        "--exclude-module", "tensorflow",
    ]
    if icns:
        cmd += ["--icon", icns]
    cmd.append(os.path.join(ROOT, "gui_qt.py"))  # 入口

    print("=" * 55)
    print("  Building LNU-LibSeat (macOS .app) ...")
    print("=" * 55)
    subprocess.check_call(cmd)

    # --- Step 4: 清理 venv ---
    print("[*] 清理 build venv...")
    shutil.rmtree(VENV_DIR, ignore_errors=True)

    app_src = os.path.join(ROOT, "dist", f"{APP_NAME}.app")
    if not os.path.isdir(app_src):
        sys.exit(f"[ERROR] 未生成 .app: {app_src}")

    # --- Step 5: 组装发行夹 ---
    if os.path.exists(DIST_DIR):
        shutil.rmtree(DIST_DIR)
    os.makedirs(DIST_DIR)

    # .app 移入发行夹
    shutil.move(app_src, os.path.join(DIST_DIR, f"{APP_NAME}.app"))
    print(f"[OK] {APP_NAME}.app 已放入发行夹")
    # PyInstaller 同时产出的 onedir 文件夹（非 .app）删掉，避免混淆
    shutil.rmtree(os.path.join(ROOT, "dist", APP_NAME), ignore_errors=True)

    # 外置可编辑 config.py（与 .app 同级 -> 对应 core.paths.app_data_dir）
    with open(os.path.join(DIST_DIR, "config.py"), "w", encoding="utf-8") as f:
        f.write(CLEAN_CONFIG)
    print("[OK] 干净 config.py 模板已写入（无个人数据）")

    # info/（座位索引）
    src_info = os.path.join(ROOT, "info")
    if os.path.exists(src_info):
        shutil.copytree(src_info, os.path.join(DIST_DIR, "info"))
        print("[OK] info/ 已复制")

    # logs/
    os.makedirs(os.path.join(DIST_DIR, "logs"), exist_ok=True)
    print("[OK] logs/ 已创建")

    # 解除限制脚本
    cmd_path = os.path.join(DIST_DIR, "首次运行请先双击我.command")
    with open(cmd_path, "w", encoding="utf-8") as f:
        f.write(UNLOCK_COMMAND)
    os.chmod(cmd_path, 0o755)
    print("[OK] 解除限制脚本已写入")

    # 使用说明
    with open(os.path.join(DIST_DIR, "使用说明.txt"), "w", encoding="utf-8") as f:
        f.write(USAGE_TXT)
    print("[OK] 使用说明.txt 已写入")

    # --- Step 6: ditto 压 zip（保留 .app 符号链接 / 权限 / ad-hoc 签名）---
    zip_path = os.path.join(ROOT, "dist", f"{DIST_NAME}.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    print(f"[*] 用 ditto 打包 {DIST_NAME}.zip ...")
    subprocess.check_call([
        "ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
        DIST_DIR, zip_path,
    ])
    print(f"[OK] {DIST_NAME}.zip 创建成功")

    print()
    print("=" * 55)
    print("  构建完成！")
    print(f"  发行夹: dist/{DIST_NAME}/")
    print(f"  压缩包: dist/{DIST_NAME}.zip")
    print()
    print("  分发给用户：发送 zip；用户解压后右键运行")
    print("  「首次运行请先双击我.command」即可。")
    print("=" * 55)


if __name__ == "__main__":
    build()
