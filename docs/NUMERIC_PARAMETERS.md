# 数字参数参考手册

> 📦 适用于 **LNU-LibSeat v5.0.0**
> 项目中所有超时、延迟、重试次数、阈值等数字参数的完整清单。

[← 返回 README](../README.md) ·
[快速上手](QUICKSTART.md) ·
[反馈消息](FEEDBACK_MESSAGES.md) ·
[配置详解](CONFIGURATION.md) ·
[验证码引擎](CAPTCHA_YOLO4_SIAMESE.md) ·
[GUI 架构](GUI_QT_ARCHITECTURE.md)

---

## 一、定时与调度（`main.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| `PREP_LEAD_SECONDS` | `30` 秒 | main.py:24 | 开火前 30 秒开始准备浏览器（06:29:30） |
| `SEAT_LOCK_LEAD_SECONDS` | `6` 秒 | main.py:25 | 开火前 6 秒开始锁座（06:29:54） |
| `MAINTENANCE_RETRY_INTERVAL_SECONDS` | `120` 秒 | main.py:26 | 系统维护时重试间隔（2 分钟） |
| 默认开火时间 | `06:30:00` | main.py | GUI 默认预约时间（用户可自定义） |
| `HEARTBEAT_INTERVAL` | `1800` 秒 | main.py:152 | 长等待时心跳日志间隔（30 分钟） |
| 精确等待阈值 | `0.02` 秒 | main.py:183 | 剩余 <20ms 时切换到忙等待 |
| 忙等待 sleep | `0.01` 秒 | main.py:185 | 最后 20ms-500ms 阶段的 sleep 间隔 |
| 开火延迟 | `2` 秒 | main.py:382 | **关键**：到达开火时间后额外等 2 秒，确保服务器已切换状态 |
| 账号启动错开 | `8` 秒/账号 | main.py:724 | 多账号启动间隔，避免同时请求 |
| `MAX_ACCOUNTS` | `2` | main.py:794 | 默认最大并发账号数 |
| 线程轮询间隔 | `0.5` 秒 | main.py:832 | 主线程等待子线程的轮询间隔 |
| 线程 join 超时 | `5` 秒 | main.py:842 | 关闭时等待线程退出的超时 |

---

## 二、浏览器驱动（`core/driver.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 页面加载超时 | `30` 秒 | driver.py:154,167,183 | `set_page_load_timeout`，三种启动方式都相同 |

---

## 三、锁座阶段（`logic/booker.py`）

### 超时与等待

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 默认 WebDriverWait | `5` 秒 | booker.py:174 | SeatBooker 实例的通用元素等待超时 |
| 座位查找超时 | `5` 秒 | booker.py (XPath wait) | 等待座位元素出现的超时 |
| 弹窗轮询超时 | `3` 秒 | booker.py:399 | 点击座位后等待预约弹窗出现的最长时间 |
| 弹窗轮询间隔 | `0.1` 秒 | booker.py:420 | 每 100ms 检查一次弹窗 |
| 关弹窗后等待 | `0.1` 秒 | booker.py:362 | 关闭拦截弹窗后等 100ms 再重试点击 |
| 开始时间点击超时 | `1.5` 秒 | booker.py:434 | 点击开始时间标签的超时（fail-fast） |
| 时间轴渲染等待 | `0.3` 秒 | booker.py:443 | 选完开始时间后等 300ms，确保右侧时间轴渲染 |
| 结束时间点击超时 | `1.5` 秒 | booker.py:447 | 点击结束时间标签的超时（fail-fast） |

### 关键词检测

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 闪电检测关键词 | 10 个 | booker.py:379-381 | `没有可用时间 没有可约时间 约满 不可预约 当前不可用 无法预约 已满 已被 不可用 没有可用` |
| 轮询检测关键词 | 10 个 | booker.py:391-394 | 同上，顺序略不同 |
| `_kw_display` 映射 | 2 条 | booker.py:373-376 | `不可用→该座位不可用` `没有可用时间→当前的座位已经没有可用时间啦` |

---

## 四、验证码阶段（`logic/booker.py`）

### 验证码识别与读取

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 验证码图片读取超时 | `1.0` 秒 | booker.py:533 | `_read_captcha_images` 默认超时 |
| 图片读取轮询间隔 | `0.05` 秒 | booker.py:553 | 每 50ms 检查图片是否加载完成 |
| 验证码弹窗等待 | `3` 秒 | booker.py:640 | `pre_solve_captcha` 中等待验证码弹窗容器 |
| 预解码图片读取超时 | `1.2` 秒 | booker.py:652 | 预解码阶段读取验证码图片的超时 |

### 闪电提交（`fire_captcha_blitz`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 确认按钮等待循环 | `60` 次 × `0.05` 秒 = `3` 秒 | booker.py:697-698 | 等待确认按钮可点击 |
| JS 回退点击阈值 | `10` 次（0.5 秒后） | booker.py:700 | ActionChains 失败后切换 JS 点击 |
| 验证码结果超时 | `3.0` 秒 | booker.py:796 | 闪电提交后等待验证结果 |
| 二次提交检查 | `0.3` 秒 | booker.py:809 | 检查提交按钮是否仍可点击 |

### 验证码确认（`_wait_captcha_result`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 轮询超时 | `3.2` 秒 | booker.py:293 | 等待验证码提交反馈的最长时间 |
| 轮询间隔 | `0.06` 秒 | booker.py:293 | 每 60ms 检查一次反馈 |
| page_source 扫描间隔 | `0.5` 秒 | booker.py:321 | UI 选择器无结果时，每 500ms 扫一次 page_source |

### 验证码刷新

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 刷新后等待超时 | `1.0` 秒 | booker.py:877 | `_refresh_click_captcha` 刷新后等新图片 |
| 关弹窗按钮等待 | `0.1` 秒/个 | booker.py:866 | 每点击一个 message-box 按钮后等 100ms |

---

## 五、预约结果检查（`logic/booker.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 结果文本等待超时 | `3` 秒 | booker.py:928 | `check_result` 中 WebDriverWait 等待预约结果 |
| 轮询频率 | `0.1` 秒 | booker.py:928 | 预约结果检查的 poll_frequency |
| 座位网格等待超时 | `5.0` 秒 | booker.py:1001 | `ensure_on_seat_grid` 等待座位元素 |
| 自选座位按钮等待 | `3` 秒 | booker.py:1007 | 等待"自选座位"按钮 |
| 自选座位点击后等待 | `0.3` 秒 | booker.py:1010 | 点击后等页面跳转 |
| reserve-box 消失等待 | `1` 秒 | booker.py:1052 | 点击关闭按钮后等弹窗消失 |
| ESC 关弹窗后等待 | `0.3` 秒 | booker.py:1067 | 按 ESC 关弹窗后等 300ms |

---

## 六、登录认证（`logic/auth.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 默认 WebDriverWait | `10` 秒 | auth.py:14 | Authenticator 实例通用超时 |
| 登录页输入框等待 | `10` 秒 | auth.py:63 | 等待登录页面加载 |
| 网络错误后等待 | `5` 秒 | auth.py:78 | 检测到网络错误页后等 5 秒再刷新 |
| 刷新后等待 | `3` 秒 | auth.py:80 | 刷新页面后等 3 秒加载 |
| 登录重试次数 | `5` 次 | auth.py:84 | 最多重试 5 次登录 |
| 输入框未找到重试等待 | `3` 秒 | auth.py:99 | 输入框未找到时等 3 秒再重试 |
| 验证码图片轮询 | `10` 次 × `0.3` 秒 = `3` 秒 | auth.py:116-127 | 等待验证码图片加载 |
| 验证码图片未找到等待 | `0.3` 秒 | auth.py:129 | 图片元素不存在时等 300ms |
| 验证码刷新后等待 | `2` 秒 | auth.py:135 | 点击验证码图片刷新后等 2 秒 |
| 验证码长度校验 | `4` 位 | auth.py:143 | OCR 结果必须是 4 位字符 |
| 验证码长度不对时等待 | `1` 秒 | auth.py:146 | 重新刷新验证码前等 1 秒 |
| 登录后重定向等待 | `3` 秒 | auth.py:162 | 等待登录后跳转（检查 header-username） |
| 异常后等待 | `1` 秒 | auth.py:200,217 | 登录流程异常后等 1 秒 |

---

## 七、页面导航（`logic/navigator.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 默认 WebDriverWait | `10` 秒 | navigator.py:15 | 导航通用超时 |
| 校区选择后等待 | `0.5` 秒 | navigator.py:20 | 选完校区下拉框后等 500ms |
| 自习室点击重试 | `3` 次 | navigator.py:27 | 处理 stale element 的重试次数 |
| 滚动后等待 | `0.2` 秒 | navigator.py:30 | 滚动元素到视图后等 200ms |
| stale element 重试等待 | `0.5` 秒 | navigator.py:35 | stale element 异常后等 500ms |
| 一般点击异常等待 | `1` 秒 | navigator.py:38 | 其他点击异常后等 1 秒 |

---

## 八、邮件通知（`core/notifications.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| SMTP SSL 端口 | `465` | notifications.py:56 | SMTP 连接端口 |
| SMTP 连接超时 | `10` 秒 | notifications.py:56 | 连接超时 |

---

## 九、日志系统（`core/logger.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 单文件最大大小 | `10 MB` | logger.py:88,152 | `maxBytes=10*1024*1024` |
| 备份文件数量 | `5` 个 | logger.py:88,152 | `backupCount=5`，最多保留 5 个旧日志 |

---

## 十、屏幕录制（`core/screen_recorder.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 默认帧率 | `5` FPS | screen_recorder.py:25 | 录屏帧率 |
| 线程 join 超时 | `3` 秒 | screen_recorder.py:131 | 停止录制时等待线程退出 |

---

## 十一、验证码 API（`core/captcha_api.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| TTShiTu type_id | `27` | captcha_api.py:19 | 点击 1-4 坐标验证码的 API 类型 |
| HTTP 请求超时 | `20` 秒 | captcha_api.py:20 | API 默认超时 |
| 裁剪边距 | `6` 像素 | captcha_api.py:32 | 合并提示图+背景图时的裁剪边距 |
| 重试间隔（网络错误） | `0.5` 秒 | captcha_api.py:99 | API 调用失败后重试间隔 |
| 无人值守等待 | `0.8` 秒 | captcha_api.py:108 | API 报告工人不足时的等待 |
| JPEG 质量 | `92` | captcha_api.py:134 | 发送图片的 JPEG 压缩质量 |
| 错误上报超时 | `10` 秒 | captcha_api.py:170 | 错误报告 API 的超时 |

---

## 十二、验证码 AI（`core/captcha_gemini.py` / `captcha_qwen.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| HTTP 请求超时 | `30` 秒 | gemini.py:21, qwen.py:22 | AI API 默认超时 |
| max_tokens / maxOutputTokens | `512` | gemini.py:89, qwen.py:84 | 最大输出 token 数 |
| temperature | `0` | gemini.py:88, qwen.py:83 | 确定性输出（不随机） |

---

## 十三、本地 YOLO+Siamese 验证码模型

### 时间窗口（`logic/booker.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 激活窗口开始 | `06:30:00` | booker.py:38 | 本地模型仅在此窗口内启用 |
| 激活窗口结束 | `06:35:00` | booker.py:39 | 窗口外自动切换到 API |

### YOLO 参数（`core/captcha_click1_yolo4_siamese.py` / `captcha_yolo4_siamese.py`）

| 参数 | click1 值 | click3 值 | 位置 | 说明 |
|------|-----------|-----------|------|------|
| 输入尺寸 | `640` px | `640` px | click1:98, click3:105 | YOLO 图像输入大小 |
| 置信度阈值 | `0.05` | `0.05` | click1:99, click3:106 | 低于此值的检测被过滤 |
| IoU 阈值 | `0.7` | `0.45` | click1:100, click3:107 | NMS 去重阈值 |
| top_k | `4` | `4` | click1:103, click3:110 | 保留的最大候选数 |
| 字符裁剪尺寸 | `60` px | `60` px | click1:104, click3:111 | Siamese 输入的裁剪大小 |
| Siamese 输入尺寸 | `112×112` | `112×112` | click1:77, click3:68 | Siamese 网络输入分辨率 |
| 填充值 | `128` | `128` | click1:84 | letterbox 灰色填充 |
| 检测数校验 | 必须 `= 4` | 必须 `= 4` | click1:239, click3:262 | 非 4 个检测 = 验证码不可用 |
| 匹配点最低要求 | — | `≥ 3` | click3:278 | click3 至少需要 3 个匹配点 |

### YOLO ONNX 推理（`core/yolo_onnx.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 默认置信度 | `0.05` | yolo_onnx.py:26 | 默认阈值 |
| 默认 IoU | `0.45` | yolo_onnx.py:26 | 默认 NMS 阈值 |
| 默认输入尺寸 | `640` px | yolo_onnx.py:26 | 默认图像大小 |
| 最大检测数 | `300` | yolo_onnx.py:44 | NMS 最多返回 300 个检测 |
| letterbox 填充色 | `114` | yolo_onnx.py:83 | YOLO 标准深灰填充 |

### OCR 后处理（`core/captcha.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 最大目标字符数 | `4` | captcha.py:75,166 | 最多提取 4 个目标字符 |
| 二值化阈值 | `150` | captcha.py:91 | 灰度图二值化阈值 |
| 文本框扩展 | `3` px | captcha.py:184 | 检测到的文本框向外扩展 3 像素 |

---

## 十四、连接池（`main.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 连接池大小 | `10` | main.py:200,579 | urllib3 连接池大小 |
| 连接超时 | `120` 秒 | main.py:209 | urllib3 连接超时（2 分钟） |
| 窗口最大化后等待 | `0.3` 秒 | main.py:219,581 | 最大化浏览器窗口后等 300ms |

---

## 十五、防休眠（`ui_qt/services/prevent_sleep.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 心跳间隔 | `30` 秒 | prevent_sleep.py:25 | 每 30 秒发送一次防休眠信号 |
| 空闲阈值 | `60` 秒 | prevent_sleep.py:26 | 用户空闲 60 秒后触发鼠标抖动 |
| 鼠标抖动距离 | `1` px | prevent_sleep.py:85 | 水平移动 1 像素后立即恢复 |

---

## 十六、日志轮转（`core/logger.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 单文件最大 | `10 MB` | logger.py:88,152 | 超过后轮转 |
| 备份数量 | `5` | logger.py:88,152 | 保留 5 个旧文件 |

---

## 十七、GUI 界面（`ui_qt/`）

### 窗口尺寸

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 默认窗口大小 | `1400×920` | app.py:69 | 主窗口初始尺寸 |
| 最小窗口大小 | `1100×760` | app.py:70 | 窗口可调整的最小尺寸 |
| 英雄圆环尺寸 | `360` px | dashboard_panel.py:17 | Logo + 倒计时圆环大小 |

### 倒计时圆环（`ui_qt/widgets/countdown_ring.py`）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 最小尺寸 | `360×360` | countdown_ring.py:38 | 圆环组件最小尺寸 |
| 渲染帧率 | `33` ms（~30fps） | countdown_ring.py:52 | 动画定时器间隔 |
| 旋转相位增量 | `0.04` rad/tick | countdown_ring.py:130 | running 模式旋转速度 |
| 脉冲相位增量 | `0.025` rad/tick | countdown_ring.py:132 | 光晕脉冲速度 |
| 外环半径比例 | `0.40` | countdown_ring.py:145 | 外环半径 = 边长 × 0.40 |
| 内环半径比例 | `0.32` | countdown_ring.py:146 | 内环半径 = 边长 × 0.32 |
| 大号倒计时字体 | `54` pt | countdown_ring.py:227 | scheduled/idle/waiting 模式 |
| 小号倒计时字体 | `38` pt | countdown_ring.py:227 | running/done 模式 |

### 计时器延迟

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 倒计时刷新延迟 | `1200` ms | app.py:235 | worker 结束后延迟刷新倒计时圆环 |

### 默认值

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 默认调度小时 | `6` | config_panel.py:313, config_io.py:57 | GUI 默认 06 时 |
| 默认调度分钟 | `30` | config_panel.py:317, config_io.py:58 | GUI 默认 30 分 |

---

## 十八、Siamese 训练参数（离线训练，不影响运行时）

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 特征维度 | `1280` | siamese_model.py:27 | MobileNetV4-Conv-Medium 输出维度 |
| Dropout | `0.2` | siamese_model.py:28 | 特征提取 dropout 率 |
| 融合层尺寸 | `5120→512→128→1` | siamese_model.py:31-36 | 融合头网络结构 |
| 输入尺寸 | `112×112` | siamese_dataloader.py:177 | 数据集输入分辨率 |
| 训练/验证比 | `0.8` | siamese_dataloader.py:70 | 80% 训练，20% 验证 |
| 随机种子 | `42` | siamese_dataloader.py:110 | 可复现的 train/val 划分 |
| 随机旋转 | `±15°` | siamese_dataLoader.py:217 | 数据增强：旋转范围 |
| HSV 色相偏移 | `±18` | siamese_dataloader.py:225 | 数据增强：色相范围 |
| HSV 饱和度 | `0.3~1.7` | siamese_dataloader.py:226 | 数据增强：饱和度范围 |
| HSV 明度 | `0.7~1.3` | siamese_dataloader.py:227 | 数据增强：明度范围 |

---

## 🔗 相关文档

- 📘 [快速上手](QUICKSTART.md) — 第一次用？从这里开始
- 💬 [反馈消息](FEEDBACK_MESSAGES.md) — 系统反馈消息详解
- 🏗️ [架构文档](ARCHITECTURE.md) — 想了解内部实现？
- ⚙️ [配置详解](CONFIGURATION.md) — 手编 config.py 时查阅
