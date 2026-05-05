# 抢座完整流程图

本文按当前代码实现绘制，覆盖单账号从启动到结束的主要路径、异常分支、重试分支和停止条件。

术语说明：

- `停止`：当前账号任务结束，通常不再尝试其他座位。
- `重启结果`：`run_browser_session()` 返回 `restart`。当前 `thread_task()` 对普通 `restart` 不做循环重启，只记录结果并结束；只有系统维护分支会按规则再次启动浏览器。
- `换座`：关闭当前弹窗后进入下一个候选座位。
- `重试当前座位`：刷新验证码或重新锁定同一个座位后继续当前座位。
- `真实黑名单处罚文本`：必须匹配“对不起，您已被加入黑名单，预约权限将在{任意日期}恢复。原因：7天内迟到违约，超过3次，加入黑名单7天”。其中日期可变，其它信息按固定结构判断。

## 1. 总控流程

```mermaid
flowchart TD
    A["main() 启动"] --> B["读取配置 USERS / TARGET_ROOM / WAIT_FOR_0630"]
    B --> C["为每个账号注册独立日志文件"]
    C --> D["为每个账号启动 thread_task 线程"]
    D --> E["账号之间间隔 5 秒启动，降低并发请求"]
    E --> F{"定时模式 WAIT_FOR_0630?"}

    F -- "是" --> G{"SCHEDULE_MODE"}
    G -- "strict" --> G1["严格模式：10:00 前抢当天；10:00 后排次日；fire_at=06:30:00"]
    G -- "custom" --> G2["自定义模式：fire_at=配置小时分钟；如果已过则排次日"]
    G1 --> H["计算 prep_at=fire_at-30s / seat_lock_at=fire_at-6s / close_at=22:00"]
    G2 --> H
    H --> I["wait_until(prep_at)：等待准备启动浏览器"]
    I -- "等待中 stop_event" --> Z1["当前账号线程结束"]
    I -- "到时" --> J["run_browser_session(schedule, wait_for_fire=True)"]

    F -- "否" --> K["立即模式：run_browser_session(schedule=None, wait_for_fire=False)"]

    J --> L{"浏览器会话结果"}
    K --> L

    L -- "success" --> Z2["记录成功，账号任务结束"]
    L -- "stopped" --> Z3["账号任务结束"]
    L -- "restart" --> Z4["普通重启结果：当前实现记录后结束"]
    L -- "maintenance_retry_at_fire" --> M["等待 fire_at"]
    M -- "到时" --> N["重启浏览器，按立即模式抢座"]
    N --> L
    L -- "maintenance_retry_later" --> O{"是否已到 close_at?"}
    O -- "是" --> Z5["停止维护重试，账号任务结束"]
    O -- "否" --> P["等待最多 120 秒后再次启动浏览器"]
    P --> N
```

## 2. 浏览器会话流程

```mermaid
flowchart TD
    A["run_browser_session()"] --> B["创建本次 session_dir"]
    B --> C["get_driver() 创建浏览器"]
    C --> D["放大 Selenium 连接池"]
    D --> E["最大化窗口"]
    E --> F{"启动录屏成功?"}
    F -- "是" --> G["录屏保存到 session_dir/recordings"]
    F -- "否" --> G1["记录警告，继续无录屏运行"]
    G --> H["Authenticator.login()"]
    G1 --> H

    H -- "登录成功" --> I["创建 SeatBooker 并绑定 session_dir"]
    H -- "maintenance_defer" --> R1["返回 maintenance_retry_at_fire"]
    H -- "maintenance_retry_later" --> R2["返回 maintenance_retry_later"]
    H -- "stop_event 已触发" --> R3["返回 stopped"]
    H -- "普通登录失败" --> R4["返回 restart"]

    I --> J{"定时会话 wait_for_fire && schedule?"}

    J -- "是" --> K["登录后检查已有预约/当天次数"]
    K -- "已有 已预约/履约中 或 当天 >= 3 次" --> S1["返回 stopped"]
    K -- "无有效预约" --> L["enter_room() 提前进入目标自习室"]
    L -- "成功" --> M["run_timed_priority_attack(schedule)"]
    L -- "失败" --> L2["立即重试 enter_room() 一次"]
    L2 -- "仍失败" --> R5["返回 restart"]
    L2 -- "成功" --> M

    J -- "否" --> N["立即模式：检查已有预约/当天次数"]
    N -- "已有 已预约/履约中 或 当天 >= 3 次" --> S2["返回 stopped"]
    N -- "无有效预约" --> O["enter_room() 进入目标自习室"]
    O -- "失败" --> R6["返回 restart"]
    O -- "成功" --> P["run_timed_priority_attack(schedule=None)"]

    M --> Q{"抢座结果"}
    P --> Q
    Q -- "success" --> T1["发送成功邮件，返回 success"]
    Q -- "stopped" --> T2["返回 stopped"]
    Q -- "all_failed" --> T3["返回 stopped"]
    Q -- "restart" --> T4["返回 restart"]

    R1 --> FIN["finally：停止录屏，导出 session.log，关闭浏览器"]
    R2 --> FIN
    R3 --> FIN
    R4 --> FIN
    R5 --> FIN
    R6 --> FIN
    S1 --> FIN
    S2 --> FIN
    T1 --> FIN
    T2 --> FIN
    T3 --> FIN
    T4 --> FIN
```

## 3. 登录流程

```mermaid
flowchart TD
    A["login(account,password)"] --> B["打开 libseat 登录页"]
    B --> C{"页面正文包含系统维护?"}
    C -- "是" --> C1{"maintenance_mode"}
    C1 -- "defer_until_fire" --> C2["last_failure=maintenance_defer，返回 False"]
    C1 -- "retry_later" --> C3["last_failure=maintenance_retry_later，返回 False"]
    C1 -- "stop" --> C4["触发 stop_event；last_failure=maintenance_stop；返回 False"]
    C -- "否" --> D{"页面显示网络出错/请稍后再试?"}
    D -- "是" --> D1["等待 5 秒，刷新页面，再等 3 秒"]
    D -- "否" --> E["进入最多 5 次登录循环"]
    D1 --> E

    E --> F{"stop_event 已触发?"}
    F -- "是" --> F1["last_failure=stopped，返回 False"]
    F -- "否" --> G["查找账号输入框"]
    G -- "找不到" --> G1["刷新页面，等待 3 秒，进入下一次登录尝试"]
    G1 --> E
    G -- "找到" --> H["填写账号和密码"]
    H --> I["轮询 10 次等待验证码图片 base64"]
    I -- "验证码图片仍为空" --> I1["点击验证码图片刷新，等待 2 秒，进入下一次登录尝试"]
    I1 --> E
    I -- "拿到图片" --> J["本地识别登录验证码"]
    J --> K{"识别结果长度为 4?"}
    K -- "否" --> K1["点击图片刷新，等待 1 秒，进入下一次登录尝试"]
    K1 --> E
    K -- "是" --> L["填写验证码，点击登录按钮"]
    L --> M{"3 秒内出现 header-username?"}
    M -- "是" --> OK["登录成功，返回 True"]
    M -- "否" --> N["读取 el-message / message-box / notification 错误提示"]
    N --> O{"错误提示是系统维护?"}
    O -- "是" --> C1
    O -- "否，有错误提示" --> P["记录登录失败提示"]
    O -- "否，无错误提示" --> P1["记录点击后无反应，可能验证码错"]
    P --> Q["点击验证码图片刷新，清空验证码输入框"]
    P1 --> Q
    Q --> E

    E -- "5 次都未成功" --> FAIL["last_failure=login_failed，返回 False"]
```

## 4. 已有预约与当天次数检查

```mermaid
flowchart TD
    A["has_active_reservation()"] --> B["点击 我的预约"]
    B -- "按钮找不到" --> C["跳过检查：返回 False，继续抢座"]
    B -- "点击成功" --> D["等待 2 秒，等待表格渲染"]
    D --> E{"状态表头可见?"}
    E -- "否" --> E1["再次点击 我的预约 并等待 2 秒"]
    E -- "是" --> F["轮询 4 次查找 已预约/履约中"]
    E1 --> F
    F -- "找到" --> G["返回 True：停止当前账号抢座"]
    F -- "没找到" --> H["统计当天预约记录总数"]
    H --> I{"当天记录数 >= 3?"}
    I -- "是" --> J["返回 True：停止当前账号抢座"]
    I -- "否" --> K["点击 自选座位 返回选座页"]
    K --> L["返回 False：继续抢座"]
    A -- "检查过程异常" --> M["尝试返回 自选座位"]
    M --> L
```

## 5. 进房流程

```mermaid
flowchart TD
    A["enter_room(campus, room)"] --> B["尝试点击校区下拉框"]
    B -- "成功" --> C["选择目标校区"]
    B -- "失败或无需切换" --> D["继续"]
    C --> D
    D --> E["查找 room-name 包含目标自习室名称的元素"]
    E -- "找不到" --> F["返回 False"]
    E -- "找到" --> G["滚动到中间并 JS 点击自习室"]
    G --> H{"出现 seat-name 座位元素?"}
    H -- "是" --> I["返回 True"]
    H -- "否/超时/异常" --> F
```

## 6. 座位候选列表与座位循环

```mermaid
flowchart TD
    A["run_timed_priority_attack()"] --> B["读取 PREFER_SEATS 和 info/{TARGET_ROOM}.txt"]
    B --> C["标准化座位号：001 -> 1"]
    C --> D["过滤不在房间清单内的首选座位"]
    D --> E["把剩余房间座位随机打乱作为兜底"]
    E --> F{"候选座位数 > 0?"}
    F -- "否" --> OUT1["返回 all_failed"]
    F -- "是" --> G["写入 session_dir/抢座顺序.txt"]
    G --> H{"定时模式有 seat_lock_at?"}
    H -- "是" --> I["wait_until(seat_lock_at)"]
    I -- "stop_event" --> OUT2["返回 stopped 或 restart"]
    I -- "到时" --> J["进入座位循环"]
    H -- "否" --> J

    J --> K{"还有下一个候选座位?"}
    K -- "否" --> OUT3["全部座位尝试完，返回 all_failed"]
    K -- "是" --> L["取下一个座位：先首选，后随机兜底"]
    L --> M{"session_stop 已触发?"}
    M -- "是且全局 stop_event" --> OUT4["返回 stopped"]
    M -- "是但非全局停止" --> OUT5["返回 restart"]
    M -- "否" --> N["select_time_and_wait() 锁座并选择起止时间"]
    N -- "失败" --> K
    N -- "成功" --> O{"fire_at 是否已经触发过?"}
    O -- "否" --> P["wait_until(fire_at)"]
    P -- "stop_event" --> P1["关闭预约弹窗，返回 stopped 或 restart"]
    P -- "到时" --> P2["额外等待 1 秒，确保服务器放座"]
    P2 --> Q["fire_submit_trigger() 点击 立即预约"]
    O -- "是" --> Q
    Q -- "失败" --> Q1["关闭弹窗，换下一个座位"]
    Q1 --> K
    Q -- "成功" --> R["进入验证码循环"]
    R --> S{"验证码/提交结果"}
    S -- "success" --> OUT6["返回 success 和座位号"]
    S -- "真实黑名单处罚文本 或 全局停止" --> OUT7["返回 stopped"]
    S -- "当前座位被拒绝/验证码耗尽" --> K
```

## 7. 单个座位锁定与时间选择

```mermaid
flowchart TD
    A["select_time_and_wait(seat,start,end)"] --> B["清理验证码弹窗/预约弹窗/遮罩"]
    B --> C["按精确座位号查找 seat-name"]
    C -- "找不到或不可点击" --> F1["失败：换下一个座位"]
    C -- "点击被遮挡" --> C1["关闭遮挡弹窗，JS 强点一次"]
    C1 -- "仍失败" --> F1
    C -- "点击成功" --> D["扫 page_source 快速失败关键词"]
    D -- "命中 没有可用时间/约满/不可预约/已满/已被/不可用" --> F2["关闭弹窗，失败：换下一个座位"]
    D -- "未命中" --> E["3 秒内等待 reserve-box 预约弹窗，同时监听失败 toast"]
    E -- "失败 toast 命中" --> F3["关闭残留弹窗，失败：换下一个座位"]
    E -- "3 秒无预约弹窗" --> F4["失败：换下一个座位"]
    E -- "预约弹窗出现" --> G["选择开始时间，timeout=1s"]
    G -- "开始时间不存在/不可选" --> F5["关闭弹窗，失败：换下一个座位"]
    G -- "成功" --> H["等待 0.3 秒，等结束时间列渲染"]
    H --> I["选择结束时间，timeout=1s"]
    I -- "结束时间不存在/不可选" --> F6["关闭弹窗，失败：换下一个座位"]
    I -- "成功" --> OK["锁座成功：返回 True"]
```

## 8. 验证码与提交分支

```mermaid
flowchart TD
    A["进入验证码循环"] --> B["max_retries = API窗口内 5 次；否则本地 OCR 10 次"]
    B --> C{"还有验证码尝试次数?"}
    C -- "否" --> OUT1["关闭验证码和预约弹窗，换下一个座位"]
    C -- "是" --> D["pre_solve_captcha(max_retries=1)"]

    D -- "5 秒内没有验证码弹窗" --> E["captcha_passed=True，直接 check_result()"]
    D -- "未解析成功" --> D1["刷新验证码，进入下一次验证码尝试"]
    D1 --> C
    D -- "解析成功" --> F["fire_captcha_blitz()"]

    F --> G{"确认/提交是否通过?"}
    G -- "False" --> H["上报 API 错误（若有 api_id）"]
    H --> I{"验证码弹窗还在吗?"}
    I -- "不在" --> J["重新锁定同一座位并再次点击立即预约"]
    J -- "重新锁定/触发失败" --> OUT2["submit_rejected：关闭弹窗，换下一个座位"]
    J -- "成功" --> C
    I -- "还在" --> K["刷新验证码，进入下一次验证码尝试"]
    K --> C

    G -- "True" --> L["check_result() 读取真实反馈组件"]
    E --> L
    L --> M{"结果 status"}
    M -- "success" --> OUT3["抢座成功，返回 success"]
    M -- "真实黑名单处罚文本" --> OUT4["停止当前账号，返回 stopped"]
    M -- "retry_captcha" --> N["验证码错误/系统繁忙/请稍后/请重试/操作频繁"]
    N --> O{"验证码弹窗还在吗?"}
    O -- "还在" --> O1["刷新验证码，继续当前座位"]
    O1 --> C
    O -- "不在" --> O2["重新锁定同一座位并再次点击立即预约"]
    O2 -- "成功" --> C
    O2 -- "失败" --> OUT2
    M -- "failed 或 check_timeout" --> OUT2
```

## 9. 验证码内部细节

```mermaid
flowchart TD
    A["pre_solve_captcha()"] --> B["等待 .captcha-modal-container 最多 5 秒"]
    B -- "没出现" --> NOCAP["返回 no_captcha=True"]
    B -- "出现" --> C["截图 1_captcha_popup"]
    C --> D{"是否使用图鉴 API?"}
    D -- "FORCE_API_ALWAYS=True 或 06:30-06:35" --> E["提取目标文字图和背景图"]
    D -- "否" --> E
    E -- "图片未加载" --> F["刷新验证码，本轮解析失败"]
    E -- "图片正常" --> G{"API 可用且在 API 窗口?"}
    G -- "是" --> H["图鉴 API 求解"]
    H -- "成功" --> I["转换为背景元素中心偏移坐标，带 api_id"]
    H -- "失败" --> J["回退本地 ddddocr"]
    G -- "否" --> J
    J -- "成功" --> K["转换为背景元素中心偏移坐标"]
    J -- "失败" --> F
    I --> OK["返回 solved=True"]
    K --> OK

    OK --> L["fire_captcha_blitz()"]
    L --> M["ActionChains 按偏移点击所有文字"]
    M --> M1["截图 2_text_clicked"]
    M1 --> M2["最多 3 秒等待确认按钮可用"]
    M2 -- "1.5 秒还无按钮" --> M3["JS 按坐标补点"]
    M3 --> M2
    M2 -- "按钮不可用/不存在" --> FAIL1["返回 False"]
    M2 -- "按钮可用" --> M4["点击确认按钮"]
    M4 --> M5["截图 3_confirm_clicked"]
    M5 --> M6{"page_source 立即出现 验证码错误/请重试?"}
    M6 -- "是" --> FAIL2["上报 API 错误，返回 False"]
    M6 -- "否" --> M7["等待验证码结果最多 2 秒"]
    M7 -- "验证码弹窗消失" --> M8["验证码通过"]
    M7 -- "出现失败关键词" --> FAIL3["必要时上报 API 错误，返回 False"]
    M7 -- "超时且弹窗未消失" --> FAIL4["截图 captcha_confirm_timeout，返回 False"]
    M8 --> M9["尝试二次点击 立即预约；找不到则认为已自动提交"]
    M9 --> DONE["返回 True"]
```

## 10. 预约结果分类

```mermaid
flowchart TD
    A["check_result() 等待真实反馈组件 3 秒"] --> B{"反馈文本命中哪类?"}
    B -- "预约成功 / 有效预约" --> S["status=success；关闭弹窗；返回成功"]
    B -- "真实黑名单处罚文本：对不起；已被加入黑名单；预约权限将在任意日期恢复；固定原因" --> BL["status=blacklist；截图 blacklist；关闭弹窗；停止当前账号"]
    B -- "验证码错误 / 系统繁忙 / 请稍后 / 请重试 / 操作过于频繁" --> R["status=retry_captcha；继续当前座位验证码流程"]
    B -- "已有预约 / 预约失败" --> F["status=failed；截图 booking_failed；关闭弹窗；换下一个座位"]
    B -- "3 秒没有有效反馈" --> T["status=failed, text=check_timeout；换下一个座位"]
    B -- "其它未知文本" --> U["status=failed；截图 unknown_result；换下一个座位"]
```

结果状态汇总：

| 出现位置 | 触发条件 | 下一步 |
| --- | --- | --- |
| 登录前检查 | 页面含系统维护 | 按 maintenance_mode：等 fire_at、稍后重试、或停止所有任务 |
| 登录循环 | 5 次登录都失败 | 返回 `restart`，当前账号任务结束 |
| 已有预约检查 | 有 `已预约` 或 `履约中` | 当前账号停止 |
| 当天次数检查 | 当天预约记录数 `>= 3` | 当前账号停止 |
| 进房 | 两次进入目标自习室失败 | 返回 `restart`，当前账号任务结束 |
| 锁座 | 座位不存在、不可点击、时间不可选、无预约框、已满等 | 换下一个座位 |
| 点击立即预约 | 找不到/点不了提交按钮 | 换下一个座位 |
| 验证码解析 | 图片未加载、API/OCR 解析失败 | 刷新验证码，继续当前座位 |
| 验证码确认 | 验证码错误/请重试 | 上报 API 错误，刷新或重锁当前座位 |
| 预约结果 | `success` | 发送成功邮件，任务结束 |
| 预约结果 | `blacklist`，且文本匹配“对不起，您已被加入黑名单，预约权限将在{任意日期}恢复。原因：7天内迟到违约，超过3次，加入黑名单7天” | 当前账号立刻停止 |
| 预约结果 | 只含规则说明，例如“连续或7天内累计3次违约，将被列入黑名单7天” | 不按黑名单停止；按其它结果继续分类 |
| 预约结果 | 只含不完整黑名单字样，例如“账号已被加入黑名单，暂不能预约” | 不按黑名单停止；按其它结果继续分类 |
| 预约结果 | `retry_captcha` | 刷新验证码或重锁当前座位 |
| 预约结果 | `failed` / `check_timeout` | 换下一个座位 |
| 座位循环 | 所有首选和兜底座位都失败 | 当前账号停止 |

## 11. 文件和截图产物

```mermaid
flowchart TD
    A["每次浏览器会话"] --> B["logs/sessions/{timestamp}_{account}/"]
    B --> C["session.log：本次会话日志切片"]
    B --> D["recordings/session_*.mp4：录屏，失败则跳过"]
    B --> E["抢座顺序.txt：首选和兜底座位顺序"]
    B --> F["截图"]
    F --> F1["1_captcha_popup"]
    F --> F2["2_text_clicked"]
    F --> F3["3_confirm_clicked"]
    F --> F4["4_result_success/failed/blacklist/retry_captcha"]
    F --> F5["booking_failed / blacklist / check_timeout / unknown_result"]
```
