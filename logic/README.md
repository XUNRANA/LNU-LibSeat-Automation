# logic/ — 业务逻辑层

抢座核心流程：登录 → 进自习室 → 选座 + 验证码 + 提交 → 结果判定。

| 文件 | 职责 |
|------|------|
| `auth.py` | 自动登录（`Authenticator`）：填账号密码、识别登录验证码、维护期检测 |
| `navigator.py` | 校区 / 自习室切换、进房（`enter_room`） |
| `booker.py` | 选座、点选验证码求解与点击、提交、预约结果检测（核心，最大文件） |
| `result_classifier.py` | 预约结果分类纯函数（`classify_booking_result` / `is_blacklist_feedback` / `is_stop_booking_feedback`），无副作用、可单测 |

> 多线程调度与单浏览器会话策略在仓库根的 [`main.py`](../main.py)；
> 系统反馈文本 → 程序行为的映射见 [`docs/FEEDBACK_MESSAGES.md`](../docs/FEEDBACK_MESSAGES.md)。
> 改动本目录后建议做真机端到端冒烟（见 [CONTRIBUTING](../CONTRIBUTING.md)）。
