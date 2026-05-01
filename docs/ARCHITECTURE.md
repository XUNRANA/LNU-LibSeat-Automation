# 🏗️ 架构与开发文档

---

## 目录

- [整体架构](#整体架构)
- [模块依赖关系](#模块依赖关系)
- [核心流程](#核心流程)
- [各模块详解](#各模块详解)
- [关键设计决策](#关键设计决策)
- [PyInstaller 打包](#pyinstaller-打包)

---

## 整体架构

```
┌─────────────────────────────────────────────────┐
│                  main.py (入口)                   │
│     多线程调度 · 生命周期管理 · 心跳监控            │
├─────────────────────────────────────────────────┤
│              logic/ (业务逻辑层)                   │
│     auth.py · navigator.py · booker.py           │
│   登录认证 · 教室导航 · 座位预订                    │
├─────────────────────────────────────────────────┤
│              core/ (基础设施层)                    │
│  driver.py · captcha.py · captcha_api.py         │
│  screen_recorder.py · logger.py                  │
│  notifications.py · utils.py                     │
│  WebDriver · OCR · 图鉴API · 录屏 · 日志 · 通知    │
├─────────────────────────────────────────────────┤
│              config.py (配置层)                    │
│   全局参数 (账户、座位、策略、邮件)                  │
└─────────────────────────────────────────────────┘
```

**依赖规则**：上层调用下层，下层不依赖上层。`logic/` 调用 `core/` 和 `config.py`，`main.py` 调用所有层。

---

## 模块依赖关系

```
main.py
 ├── config.py                 (USERS, TARGET_ROOM, WAIT_FOR_0630, FORCE_API_ALWAYS...)
 ├── core/driver.py            (get_driver)
 │   └── config.py             (BROWSER, DRIVER_PATH...)
 ├── core/utils.py             (get_beijing_time)
 ├── core/logger.py            (get_logger) ← 所有模块共用
 ├── core/screen_recorder.py   (EdgeWindowRecorder)
 ├── core/notifications.py     (send_email)
 ├── logic/auth.py             (Authenticator.login)
 │   └── core/captcha.py       (solver.solve_base64)
 ├── logic/navigator.py        (enter_room)
 └── logic/booker.py           (SeatBooker + 点选验证码 + 截图)
     ├── core/captcha_api.py   (TTShiTuClient — 图鉴 API)
     └── core/captcha.py       (click_solver.solve — ddddocr 兜底)
```

---

## 核心流程

### 单线程任务流程 — v3.0.0 全自习室扫描策略

```
thread_task(account, ...)
 │
 ├── 阶段 0：wait_until(prep_at) → 启动浏览器
 │   ├── 创建会话文件夹 logs/sessions/<ts>_<account>/
 │   ├── 加载自习室座位索引 info/<room>.txt
 │   ├── 构建座位列表：首选有序 + 剩余随机
 │   ├── 写抢座顺序.txt
 │   ├── EdgeWindowRecorder(driver).start()
 │   ├── Authenticator(driver).login()
 │   └── enter_room(TARGET_ROOM)
 │
 ├── 阶段 1：wait_until(seat_lock_at) → 逐座位抢座
 │   └── for seat in extended_seats:
 │       ├── 快速校验：座位不在自习室清单 → 秒跳
 │       ├── select_time_and_wait(seat, start, end) → 锁定
 │       ├── wait_until(fire_at) → 准时触发
 │       ├── fire_submit_trigger() → 点击「立即预约」
 │       ├── captcha 循环（API 5次 / 本地 10次）：
 │       │   ├── pre_solve_captcha → OCR 识别
 │       │   │   ├── 图鉴 API (高峰期 或 FORCE_API_ALWAYS)
 │       │   │   └── ddddocr 本地 (兜底)
 │       │   └── fire_captcha_blitz → 点击文字 + 确定
 │       │       ├── ActionChains 精确点击
 │       │       ├── 1.5s 后 JS 兜底补点
 │       │       ├── 轮询等待按钮出现 (3s)
 │       │       └── Selenium 原生点击确定
 │       ├── check_result() → 检测结果
 │       │   ├── success → 发邮件 → 结束
 │       │   └── failed → 下一座位
 │       └── 截图四阶段全记录
 │
 └── 阶段 2：全部座位失败
     ├── recorder.stop()
     ├── 复制 session.log
     └── 退出
```

---

## 各模块详解

### `main.py` — 入口与调度

- **`build_strict_schedule()`** — 计算当日/次日抢座日程
- **`build_custom_schedule()`** — 自定义时刻定时
- **`wait_until()`** — 分段精确等待，含 30 分钟心跳
- **`run_browser_session()`** — 单次浏览器会话，创建会话文件夹
- **`run_timed_priority_attack()`** — 全自习室扫描主循环
- **`thread_task()`** — 单账号完整流程

### `core/driver.py` — WebDriver 管理

三级回退：`DRIVER_PATH` → `webdriver-manager` → SeleniumManager。

### `core/captcha.py` — 本地验证码识别

- **`CaptchaSolver`**：登录验证码，全局单例 `solver`
- **`ClickCaptchaSolver`**：点选验证码，ddddocr 检测+分类双引擎，支持多字匹配/单字回退、易混字容错

### `core/captcha_api.py` — 图鉴 API

- **`TTShiTuClient`**：拼接提示图+大图上传，解析返回坐标，坐标映射回大图坐标系
- 单例懒加载 `get_client()`，凭据内嵌

### `core/screen_recorder.py` — 浏览器录屏

- `driver.get_screenshot_as_png()` 抓帧 → OpenCV 写 MP4

### `logic/booker.py` — `SeatBooker` 类

核心方法：
- `select_time_and_wait()` — 选座 + 闪电失败检测 + 自动关闭遮挡
- `pre_solve_captcha()` — 验证码预分析（API 优先，本地兜底）
- `fire_captcha_blitz()` — ActionChains 点击文字 → 轮询按钮 → JS 兜底 → 确认提交
- `check_result()` — `EC.any_of` 多结果检测
- `_save_screenshot()` — 截图命名：`优先级_座位_重试_阶段_时间戳.png`
- `_build_solve_data()` — 像素坐标 → CSS 偏移量转换

---

## 关键设计决策

| 决策 | 理由 |
|------|------|
| **单会话深度尝试** | 单浏览器 10 座位 × N 次验证码 |
| **全自习室兜底** | 首选失败 → 随机扫描剩余全部座位 |
| **图鉴 API 优先** | 商业级识别率，ddddocr 本地免费兜底 |
| **双保险点击** | ActionChains + JS MouseEvent 补点，确保按钮激活 |
| **Vue 条件渲染适配** | `.el-button.confirm-btn` 选择器区分灰色 div 和真实按钮 |
| **会话级追溯** | 独立文件夹 / 4 阶段截图 / session.log / 抢座顺序.txt |
| **API 5 次 / 本地 10 次** | 按引擎类型差异化重试上限 |
| **seat_lock 6s 提前** | 3-4s 锁定耗时 + 2s 余量保证准时 |
| **stop_event 全链路** | Ctrl+C / GUI 停止即时响应 |
| **打包隔离 venv** | 避免全局包被误打包 |

---

## PyInstaller 打包

```powershell
python build.py
```

隔离虚拟环境方案：创建 `.build_venv/` → 安装依赖 → 打包 → 清理。输出 `dist/LNU-LibSeat-v3.0.0/` + ZIP。
