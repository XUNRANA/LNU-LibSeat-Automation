# 🏗️ 架构与开发文档

本文档面向希望理解项目内部工作原理或参与开发的贡献者。

---

## 目录

- [整体架构](#整体架构)
- [模块依赖关系](#模块依赖关系)
- [核心流程](#核心流程)
- [各模块详解](#各模块详解)
- [关键设计决策](#关键设计决策)
- [PyInstaller 打包](#pyinstaller-打包)
- [测试](#测试)
- [扩展指南](#扩展指南)

---

## 整体架构

项目采用 **三层架构**，关注点分离清晰：

```
┌─────────────────────────────────────────────────┐
│                  main.py (入口)                   │
│     多线程调度 · 生命周期管理 · 心跳监控            │
├─────────────────────────────────────────────────┤
│              logic/ (业务逻辑层)                   │
│     auth.py · navigator.py · booker.py           │
│   登录认证 · 教室导航 · 座位预订 · 失败截图          │
├─────────────────────────────────────────────────┤
│              core/ (基础设施层)                    │
│  driver.py · captcha.py · logger.py              │
│  notifications.py · utils.py                     │
│  WebDriver · OCR · 日志 · 通知 · 工具              │
├─────────────────────────────────────────────────┤
│              config.py (配置层)                    │
│   全局参数 (账户、座位、策略、邮件、SMTP)            │
└─────────────────────────────────────────────────┘
```

**依赖规则**：上层可以调用下层，下层不依赖上层。`logic/` 调用 `core/` 和 `config.py`，`main.py` 调用所有层。

所有模块统一使用 `core.logger.get_logger(__name__)` 获取 logger 实例，确保日志同时输出到控制台和文件。

---

## 模块依赖关系

```
main.py
 ├── config.py                 (USERS, TARGET_ROOM, WAIT_FOR_0630...)
 ├── core/driver.py            (get_driver)
 │   └── config.py             (BROWSER, DRIVER_PATH, HEADLESS...)
 ├── core/utils.py             (get_beijing_time)
 ├── core/logger.py            (get_logger) ← 所有模块共用
 ├── core/notifications.py     (send_email)
 │   └── config.py             (RECEIVER_EMAIL, SMTP_USER, SMTP_PASS)
 ├── logic/auth.py             (Authenticator.login)
 │   └── core/captcha.py       (solver.solve_base64)
 ├── logic/navigator.py        (enter_room)
 └── logic/booker.py           (SeatBooker + 点选验证码 + 失败截图)
     └── core/captcha.py       (click_solver.solve)
```

---

## 核心流程

### 主程序启动流程

```
main()
 │
 ├── 1. 导入配置（USERS, TARGET_ROOM, WAIT_FOR_0630...）
 ├── 2. 创建全局 stop_event (threading.Event)
 ├── 3. 对每个 USERS 中的账号：
 │      └── 创建守护线程 → thread_task(account, password, config, stop_event)
 ├── 4. 主线程阻塞等待所有子线程
 │      └── 捕获 Ctrl+C → stop_event.set()
 └── 5. finally: stop_event.set() + join(timeout=5)
```

### 单线程任务流程 (`thread_task`)

```
thread_task(account, password, time_config, stop_event)
 │
 ├── 阶段 0：等待 6:29:15 (prep_at) → 准备就绪 (含 30 分钟心跳日志)
 │   ├── 启动纯净无痕浏览器（无临时目录依赖）
 │   ├── Authenticator(driver).login(account, password, stop_event)
 │   │   ├── 打开登录页 → WebDriverWait 等页面就绪
 │   │   ├── 检测系统维护/网络异常 → 自动恢复
 │   │   ├── 模拟真人速度填写账号密码
 │   │   ├── 轮询获取验证码图片 (base64)
 │   │   ├── ddddocr OCR 识别
 │   │   ├── 填入验证码 → 点击登录
 │   │   └── 检测成功标志 (header-username)
 │   ├── enter_room(TARGET_ROOM) — 选校区 + 进自习室
 │   └── attempt_seat_selection() — 统一选座逻辑
 │       └── for seat in PREFER_SEATS:
 │           └── booker.select_time_and_wait(seat, start, end)
 │
 ├── 阶段 1：等待 6:30:00 (fire_at) → 准时 fire_submit()
 │   ├── 点击「立即预约」按钮
 │   ├── _handle_click_captcha()  ← 🆕 点选验证码处理
 │   │   ├── 检测验证码弹窗是否出现
 │   │   ├── 提取目标文字图片 + 背景大图 (base64)
 │   │   ├── click_solver.solve() — ddddocr 检测+分类
 │   │   ├── ActionChains 依次点击匹配文字位置
 │   │   ├── 点击「确定」→ 等待弹窗消失
 │   │   └── 失败自动刷新重试（最多 5 次）
 │   └── 验证码通过后尝试再次点击「立即预约」
 │
 └── 阶段 2：检查结果
     ├── booker.check_result()
     │   ├── "预约成功"/"有效预约" → 成功 ✅
     │   └── "已有预约"/"预约失败" → 失败 (自动截图) → 重试
     ├── [成功] send_email() → 检查返回值 → 结束
     └── [失败] → 重试循环 (复用 attempt_seat_selection)
```

### 精确等待策略 (`wait_until`)

| 剩余时间 | 策略 | 说明 |
|---------|------|------|
| > 5 秒 | `Event.wait(30分钟分段)` | 长时间挂起，每段输出 💓 心跳 |
| 0.5s ~ 5s | `Event.wait(0.2s)` | 短间隔轮询 |
| 20ms ~ 0.5s | `Event.wait(10ms)` | 精细轮询 |
| < 20ms | busy-wait | 极短忙等保证精度 |

所有阶段均响应 `stop_event`，可被 Ctrl+C 中断。

---

## 各模块详解

### `main.py` — 入口与调度

- **`build_strict_schedule()`** — 计算当日/次日抢座日程
- **`wait_until()`** — 分段精确等待，含 30 分钟心跳
- **`attempt_seat_selection()`** — 统一选座逻辑，准备阶段和失败重试 重试共用
- **`thread_task()`** — 单账号完整流程
- **`main()`** — 多线程调度入口

### `core/driver.py` — WebDriver 管理

**三级回退策略**：
1. `DRIVER_PATH` 手动指定 → 完整路径
2. `webdriver-manager` → 自动下载匹配版本
3. Selenium 4 内置 `SeleniumManager` → 自动解析

**关键配置**：
- `page_load_strategy = 'eager'` — DOM ready 即可，不等所有资源
- `--disable-blink-features=AutomationControlled` — C++ 层面移除 WebDriver 标识
- 自定义 User-Agent — 去除自动化泄露特征
- `excludeSwitches: ['enable-automation']` — 隐藏自动化控制条
- 页面超时 30 秒

### `core/captcha.py` — 验证码识别

**`CaptchaSolver`（登录验证码）**：
- 全局单例 `solver`，避免重复加载模型
- 输入：Base64 字符串 → 输出：识别的文本字符串（4 位字母数字）

**`ClickCaptchaSolver`（预约点选验证码）** 🆕：
- 全局单例 `click_solver`，ddddocr 检测引擎 (`det=True`) + 分类引擎 (`det=False`)
- `solve(target_bytes, bg_bytes)` → 返回按顺序的点击坐标 `[(x, y), ...]`
- 流程：识别目标文字 → 检测背景图文字区域 → 逐个裁剪 OCR → 匹配目标 → 输出坐标

### `core/logger.py` — 日志系统

- 双输出：控制台 `StreamHandler` + 文件 `RotatingFileHandler`
- 轮转策略：10MB/文件，保留 5 个备份
- 所有模块通过 `get_logger(__name__)` 获取带 handler 的 logger 实例

### `core/notifications.py` — 邮件通知

- 发件邮箱配置从 `config.py` 读取（`SMTP_USER` / `SMTP_PASS`），向后兼容默认值
- 收件邮箱从 `config.RECEIVER_EMAIL` 读取
- 通过 SMTP_SSL 协议发送，自动推断 SMTP 服务器（126/QQ）
- 返回 `True`/`False` 表示发送成功/失败，调用方检查返回值并记录日志

### `logic/auth.py` — `Authenticator` 类

- 封装完整的登录流程，支持 `stop_event` 全局中止
- 打开登录页后使用 `WebDriverWait` 等待页面就绪（不再硬等 3 秒）
- 系统维护检测 → 自动触发全局停止；网络异常 → 自动刷新恢复
- 模拟真人输入速度（逐字符输入 + 间隔），降低反爬触发概率
- 最多重试 5 次
- 验证码图片通过轮询 `<img>` 元素的 `src` 属性获取 Base64 数据
- 使用 JS 点击登录按钮避免元素遮挡问题

### `logic/navigator.py` — `enter_room` 函数

- 先切换校区（如"崇山校区图书馆"）
- 根据 `room_name` 匹配 `.room-name` CSS 类
- 使用 JS 点击确保可靠性
- 等待 `.seat-name` 出现确认加载完成

### `logic/booker.py` — `SeatBooker` 类

核心方法：
- `select_time_and_wait()` — 选座 + 选时间
- `fire_submit()` — 点击提交 + 自动处理点选验证码 + 再次提交
- `_handle_click_captcha()` 🆕 — 检测验证码弹窗 → 提取图片 → 求解 → 点击 → 确认（最多 5 次重试）
- `_refresh_click_captcha()` 🆕 — 刷新验证码图片
- `check_result()` — 使用 `EC.any_of` 检测多种弹窗结果，失败时自动截图
- `close_popup()` — 关闭预约弹窗
- `_save_failure_screenshot()` — 保存失败截图到 `logs/screenshot_{tag}_{timestamp}.png`

---

## 关键设计决策

| 决策 | 理由 |
|------|------|
| **threading 而非 asyncio** | Selenium 是同步 API；多线程简单直接 |
| **纯净无痕浏览器** | 每线程创建全新浏览器实例（`user_data_dir=None`），无历史数据干扰 |
| **stop_event 贯穿全链路** | 替代轮询 `time.sleep`，支持 Ctrl+C 快速退出 |
| **两阶段卡点** | 06:29:15 顺序完成启动+登录+选座，6:30:00 只需一次点击 |
| **JS 点击而非原生 click** | 避免悬浮层遮挡导致的 `ElementClickInterceptedException` |
| **ddddocr 单例** | 模型加载耗时，全局共享减少开销（登录 OCR + 点选检测/分类共 3 个实例） |
| **attempt_seat_selection 复用** | 准备阶段和失败重试 共用选座逻辑，消除代码重复 |
| **send_email 检查返回值** | 邮件函数内部捕获异常返回 bool，调用方据此记录日志 |
| **get_logger 统一日志** | 所有模块的日志都写入文件，不再有静默丢失 |
| **打包隔离虚拟环境** | 自动创建干净 venv，避免 Anaconda/torch 等全局包被误打包，构建快速可靠 |

---

## PyInstaller 打包

> 普通用户请直接从 [GitHub Releases](https://github.com/XUNRANA/LNU-LibSeat-Automation/releases/latest) 下载预构建的 EXE，无需自行打包！

以下内容面向需要重新构建 EXE 的开发者。

### 打包命令

```powershell
python build.py
```

> 无需提前 `pip install pyinstaller`，`build.py` 会自动处理一切。

### 打包机制

`build.py` 采用**隔离虚拟环境**方案，确保打包过程干净可靠，不受开发者本机环境影响（Anaconda、torch 等均不会被误打包）：

1. 自动创建临时虚拟环境 `.build_venv/`
2. 在该环境中仅安装 3 个必需包：`selenium`、`ddddocr`、`pyinstaller`（由 `BUILD_DEPS` 定义）
3. 在干净的虚拟环境内执行 PyInstaller 打包
4. 打包完成后自动删除 `.build_venv/`

**关键配置**：
- **`_runtime_hook.py`** — PyInstaller 运行时钩子，在 main.py 之前执行：
  - `os.chdir(exe_dir)` — 确保相对路径正确
  - `sys.path.insert(0, exe_dir)` — 确保外部 `config.py` 可导入
  - `chcp 65001` + `reconfigure(utf-8)` — 修复 Windows 控制台中文显示
- **`--exclude-module config`** — config.py 不打入 exe，保持外部可编辑
- **`--collect-all ddddocr/onnxruntime/selenium`** — 打包 OCR 模型、推理引擎、浏览器驱动管理
- 打包产物：`dist/LNU-LibSeat/` 文件夹（~320MB，主要是 ONNX 模型）

---

## 测试

### 运行单元测试

```powershell
python -m pytest -q
```

默认只运行单元测试（`-m "not smoke"`），不需要浏览器或网络。

### 运行冒烟测试

需要可用的浏览器和网络环境：

```powershell
python -m pytest -m smoke -q
```

### 测试文件说明

| 文件 | 覆盖范围 |
|------|---------|
| `tests/test_utils.py` | `get_beijing_time()` |
| `tests/test_driver_unit.py` | `_build_options()` 等纯函数 |
| `tests/test_schedule_logic.py` | `build_strict_schedule()` 和 `wait_until()` |
| `tests/test_driver_smoke.py` | 真实浏览器启动（`@pytest.mark.smoke`） |
| `tests/test_email_manual.py` | 邮件发送排版验证（手动运行） |

---

## 扩展指南

### 添加新的通知渠道

在 `core/notifications.py` 中添加新函数：
```python
def send_dingtalk(title: str, content: str) -> bool:
    # 实现钉钉通知
    ...
```

### 添加新的浏览器支持

1. 在 `core/driver.py` 的 `_build_options()` 中添加新分支
2. 在 `get_driver()` 中添加对应的 Service 和 WebDriver 类

### 添加新的自习室支持

无需改代码，只需在 `config.py` 中修改 `TARGET_ROOM` 即可。

### 修改验证码识别方案

- **登录验证码**：替换 `CaptchaSolver` 实现，保持 `solver` 全局实例和 `solve_base64` 接口不变。
- **预约点选验证码**：替换 `ClickCaptchaSolver` 实现，保持 `click_solver` 全局实例和 `solve(target_bytes, bg_bytes)` 接口不变。
