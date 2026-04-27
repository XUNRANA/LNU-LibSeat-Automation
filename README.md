# LNU-LibSeat-Automation

> **辽宁大学图书馆座位预约自动化工具** — 快速、精准地抢占目标自习室座位

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![Selenium](https://img.shields.io/badge/Selenium-4.x-green.svg)](https://selenium.dev)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](#版权与许可)
[![Release](https://img.shields.io/github/v/release/XUNRANA/LNU-LibSeat-Automation?label=Latest)](https://github.com/XUNRANA/LNU-LibSeat-Automation/releases/latest)

---

## ✨ 特性

- 🖥️ **现代化图形界面** — 全新设计的 GUI，采用 Indigo 主题配色，卡片式布局，视觉清爽
- 🧵 **多线程并发** — 多账号同时运行，分时段分工，最大化抢座成功率
- 🎯 **精确锁定** — 指定座位号 + 时间段，按优先级依次尝试
- 🔐 **验证码自动识别** — 登录验证码 OCR + 预约点选验证码双引擎破解（图鉴 API 优先，ddddocr 本地兜底）
- ⏱️ **三阶段精确卡点** — `prep_at` 启动浏览器 → `pre_fire_at` 触发验证码预分析 → `fire_at` 准时提交
- 🎯 **单会话深度尝试** — 单浏览器会话，10 个优先座位逐个尝试，每个座位最多 10 次验证码机会
- 🎥 **浏览器全程录屏** — 自动录制抢座全过程 MP4 视频（支持 headless 模式），方便复盘
- 📧 **邮件通知** — 抢座成功后自动发送战报至你的邮箱
- 📸 **失败截图** — 预约失败时自动截图保存，方便事后排查
- 🛡️ **底层防休眠与心跳守护** — 运行期间自动调用系统唤醒权限，长达10小时挂机不断网/不休眠，并附带 30 分钟心跳日志
- 🌐 **Edge / Chrome 双支持** — 兼容主流浏览器，驱动自动下载
- 📦 **EXE 免安装分发** — 下载即用，无需安装 Python

---

## 📸 真实效果展示

### GUI 主界面 — 定时模式（双账号分时段挂机）

![GUI 定时模式](docs/screenshots/gui_scheduled.png)

### 立即执行 — 自动登录 + 验证码识别 + 选座全流程

![自动抢座进行中](docs/screenshots/gui_running.png)

### 抢座成功 — 双账号同时锁定 + 邮件通知

![抢座成功](docs/screenshots/gui_success.png)

### 手机即时收到成功通知邮件

<p align="center">
  <img src="docs/screenshots/email_notification.png" width="320" alt="邮件通知">
</p>

---

## 🚨 重要警告：合理使用，切勿滥用！

> ⚠️ **请务必准时到馆签到！** 由于自动化速度极快，滥用极易触发学校系统报警。连续或 7 天内累计 3 次违约，将被列入黑名单 7 天！

---

## ⚡ 快速开始

> 🔒 隐私提示：仓库内的 `config.py` 默认是脱敏模板（无学号/密码/邮箱）。你的真实信息只会在你本机 GUI 中填写并自动保存，请勿将含个人信息的配置文件提交到 Git。

### 📋 小白必看：运行环境要求

如果这是一台全新的电脑，你**只需要满足以下 3 点**即可正常使用：

1. **操作系统**：Windows 10 或 Windows 11。
2. **浏览器**：电脑中安装有正常的 **Microsoft Edge** 或 **Google Chrome**。程序内置自动驱动匹配功能，**不需要你手工查版本下驱动**。
3. **网络畅通**：能正常打开网页进入座位预约系统。

🎯 **绝对不需要的东西**（繁杂环境都已统一打包进了 EXE）：
- ❌ **不需要** 下载安装 Python 或任何代码编辑器。
- ❌ **不需要** 配置系统环境变量或开启命令行控制台。

### 方式一：下载 EXE 直接运行（推荐）

**无需安装 Python，无需任何编程知识！**

1. 前往 [GitHub Releases](https://github.com/XUNRANA/LNU-LibSeat-Automation/releases/latest) 下载最新版 `LNU-LibSeat-v2.7.0.zip`
2. 解压到任意位置
3. 双击 `LNU-LibSeat.exe`，在 GUI 界面中填写学号、密码、座位号等（GUI 会自动保存到本地 `config.py`）
4. 点击「开始抢座」，完事！

### 方式二：Python 源码运行（开发者 / 高级用户）

```powershell
# 1. 克隆项目
git clone https://github.com/XUNRANA/LNU-LibSeat-Automation
cd LNU-LibSeat-Automation

# 2. 运行（首次运行 run.bat 会自动创建虚拟环境并安装依赖）
run.bat
```

> 📖 详细教程请查看 **[快速上手指南](docs/QUICKSTART.md)**

---

## 📖 小白使用必读指南（保姆级教程）

打开软件后，你需要正确填写以下信息才能顺利抢座：

- 🎯 **目标配置**：选好你想去的校区和自习室，并填上最多十个你最心仪的座位号（按优先级排列）。
- 👤 **账号时间**：填写你的学号和密码（注意：如果没有修改过，初始密码为 `000000`）。

> ⚠️ **重中之重**：抢座的 "左区间（开始时间）" 你可以填"现在"或者整点（如：`9:00`），但抢座的 **"右区间（结束时间）"必须填整点**，比如 `15:00`，否则学校系统是不认的！

- 📧 **成功通知**：填写你的邮箱地址，任意邮箱都行（只要邮箱存在，抢座成功就会发通知提醒你）。
- ⚙️ **执行模式**：选择"立即执行"或"定时执行"。
  - **定时执行提醒**：这里填写的是 24小时制。如果设置的预约时间大于当前时间，则认为是今天抢座；如果小于当前时间，则认为是明天的抢座！
  - **卡点启动说明**：系统会提前完成登录和页面预热，到了预约时间的 00 秒分秒不差地开始点座，并立即执行验证码识别、按顺序点字和确认提交。
  - **关于静默开关**：如果你关闭了"后台静默运行"这个开关，系统在抢座时会光明正大地弹出一个真实的浏览器窗口，你可以亲眼目睹整个浏览器的全自动化抢座详细流程！

> 💡 上方「📸 真实效果展示」章节中有完整的 GUI 界面截图，可以直观了解操作界面和运行效果。

---

## 📁 项目结构

```
LNU-LibSeat-Automation/
├── gui.py                   # 🖥️ GUI 入口（CustomTkinter 现代卡片式界面，Indigo 主题）
├── main.py                  # 程序核心：多线程调度器、单会话策略引擎
├── config.py                # ⚙️ 配置文件（由 GUI 自动生成，也可手动编辑）
├── run.bat                  # 一键启动脚本
├── build.py                 # 📦 PyInstaller 打包脚本
├── _runtime_hook.py         # PyInstaller 运行时钩子
├── core/                    # 🛠️ 基础设施层
│   ├── driver.py            #   WebDriver 创建与管理
│   ├── captcha.py           #   验证码识别（登录 OCR + 预约点选文字验证码 ddddocr 本地引擎）
│   ├── captcha_api.py       #   图鉴 (TTShiTu) 付费验证码识别 API 客户端
│   ├── screen_recorder.py   #   浏览器全程录屏（Selenium 截图 → MP4）
│   ├── logger.py            #   日志系统（控制台 + 文件轮转 + GUI 回调）
│   ├── notifications.py     #   SMTP 邮件推送
│   └── utils.py             #   时间工具
├── logic/                   # 🧠 业务逻辑层
│   ├── auth.py              #   自动登录 + 验证码处理
│   ├── navigator.py         #   校区切换 + 进入自习室
│   └── booker.py            #   选座 + 提交 + 点选验证码 + 结果检测
├── tests/                   # 🧪 测试套件
└── docs/                    # 📖 文档
    ├── QUICKSTART.md         #   快速上手教程
    ├── CONFIGURATION.md      #   配置详解
    └── ARCHITECTURE.md       #   架构与开发文档
```

## 📖 文档导航

| 文档 | 说明 |
|------|------|
| [快速上手](docs/QUICKSTART.md) | 从零开始的完整使用教程（含 EXE 模式和 Python 模式） |
| [配置详解](docs/CONFIGURATION.md) | `config.py` 各字段详细说明与参数含义 |
| [架构文档](docs/ARCHITECTURE.md) | 项目架构设计、模块关系、核心流程、开发者指南 |

---

## 📦 打包为 EXE（开发者）

> 普通用户请直接从 [Releases](https://github.com/XUNRANA/LNU-LibSeat-Automation/releases/latest) 下载，无需自行打包！

```powershell
python build.py
```

> `build.py` 会自动创建干净的临时虚拟环境，仅安装必需依赖，打包后自动清理。打包过程会自动生成干净的 `config.py` 模板，确保不会泄露任何个人信息。

打包完成后 `dist/LNU-LibSeat-vX.Y.Z/` 文件夹即为完整的分发包（版本号由 `build.py` 中的 `APP_VERSION` 决定）：
- `LNU-LibSeat.exe` — 双击运行 GUI
- `config.py` — 配置模板（首次运行 GUI 后自动覆盖）
- `logs/` — 运行日志、失败截图和录屏视频

打包脚本会自动生成 `LNU-LibSeat-vX.Y.Z.zip`，可直接上传至 GitHub Release。

---

## 🏛️ 辽宁大学图书馆官方预约规则

> 为了避免因为一时疏忽被拉进黑名单，请务必仔细阅读学校官方的规则：

**一、预约方式**
- 线上渠道：PC / 移动端登录：libseat.lnu.edu.cn
- 微信：辽宁大学图书馆公众号→服务→座位预约
- 线下渠道：保留原到馆刷卡选座方式
- 登录信息：用户账号为校园卡号，初始密码 `000000`（可通过校园网至 opac.lnu.edu.cn"我的图书馆" 修改）

**二、线上预约规则**
1. ✅ 预约后需到馆刷校园卡签到，未按时签到记为违约！
2. ✅ 允许提前 30 分钟签到，最晚不超过预约时间后 30 分钟。
3. ✅ 建议提前 10 分钟签到，特殊情况请务必及时取消预约。
4. 🚫 **连续或 7 天内累计 3 次违约，将被列入黑名单 7 天！！！**
5. ⏰ 预约开放时间：每日 6:30 - 21:30（预约当日座位）
6. 📊 每日预约 ≤ 3 次，每次最长 6 小时，每天取消 ≤ 3 次。

---

## ⚠️ 免责声明

本项目仅供**技术交流与学习**，请严格遵守学校图书馆的使用规定与相关条款。使用自动化工具可能违反网站条款或触发防护措施，**所有后果由使用者自行承担**。

## 🤝 贡献

欢迎提交 Issue 和 PR！

## 📄 版权与许可

本项目采用 MIT 许可证。
