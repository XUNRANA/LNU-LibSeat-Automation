### v3.0.0 核心特性说明

本次版本迎来**全自习室覆盖、双保险点击、会话级可追溯**三大升级，将抢座从"碰运气"进化为"地毯式扫描"。

#### 全自习室座位兜底扫描
*   **20 间自习室全覆盖**：内置辽大蒲河校区 12 间 + 崇山校区 8 间，共 20 间自习室的完整座位索引。
*   **地毯式兜底**：首选座位按用户填写顺序优先，全失败后自动随机扫描该自习室**剩余全部座位**，直到抢到或全部试完为止。
*   **快速跳过**：首选座位不在目标自习室 → 秒级跳过，不浪费 6 秒超时等待。
*   **抢座顺序存档**：每次会话自动生成 `抢座顺序.txt`，记录每个座位的尝试优先级和结果。

#### ⚡ 验证码双保险点击策略
*   **ActionChains 精确点击**：首选方案，使用真实鼠标事件点击验证码文字。
*   **JavaScript 兜底补点**：1.5 秒未命中自动启用 JS MouseEvent 派发，精确计算屏幕坐标，**双重保障确保按钮必定激活**。
*   **修复按钮选择器**：从 `.confirm-btn` 升级为 `.el-button.confirm-btn`，解决 Vue 条件渲染导致按钮找不到的经典难题。

#### 会话级完整可追溯
*   **专属会话文件夹**：每次抢座自动创建 `logs/sessions/<时间戳>_<账号>/`，包含：
    - `session.log` — 本会话完整日志
    - `抢座顺序.txt` — 座位尝试顺序清单
    - 4 阶段截图：验证码弹窗 → 点击文字 → 点击确定 → 结果反馈
    - 录屏视频 MP4
*   **截图精确命名**：`优先级_座位号_第几次_阶段_时间戳.png`，一眼定位问题。

#### 🎛️ GUI 升级
*   **图鉴 API 开关**：GUI 新增独立开关，一键切换全天 API 抢座 / 仅高峰期 API。
*   **API 5 次 / 本地 10 次**：图鉴 API 每座位最多 5 次重试，本地 OCR 保持 10 次。
*   **移除静默开关**：浏览器始终可见运行，方便实时观察。

#### ⏱️ 时序优化
*   **锁定提前量翻三倍**：座位锁定从提前 2 秒改为提前 6 秒，彻底消除因弹窗拦截导致的迟到问题。

#### 🧹 代码清理
*   砍掉静默浏览器（headless）功能
*   日志去除"优先级"话术，统一为座位号直述
*   移除 v2.5/v2.6 时代遗留的死代码

---

## 下载安装（3 步搞定）

**Step 1**：点击下方 `LNU-LibSeat-v3.0.0.zip` 下载压缩包

![下载位置](https://raw.githubusercontent.com/XUNRANA/LNU-LibSeat-Automation/master/docs/screenshots/github_release.png)

**Step 2**：解压到任意不包含中文的路径下，双击 `LNU-LibSeat.exe` 即可启动

![解压后文件夹](https://raw.githubusercontent.com/XUNRANA/LNU-LibSeat-Automation/master/docs/screenshots/folder_structure.png)

**Step 3**：在 GUI 中填写信息，点击「🔥 开始抢座」！

![GUI 界面](https://raw.githubusercontent.com/XUNRANA/LNU-LibSeat-Automation/master/docs/screenshots/gui_scheduled.png)

> 🎯 **无需安装 Python，无需配置环境变量，无需下载浏览器驱动** — 全部自动搞定！

---

## 📸 真实运行效果

### 立即执行 — 自动登录 + 验证码 OCR + 并发选座

![运行中](https://raw.githubusercontent.com/XUNRANA/LNU-LibSeat-Automation/master/docs/screenshots/gui_running.png)

### 抢座成功 — 双账号同时锁定 + 邮件通知

![抢座成功](https://raw.githubusercontent.com/XUNRANA/LNU-LibSeat-Automation/master/docs/screenshots/gui_success.png)

### 手机即时收到成功通知邮件

<p align="center">
  <img src="https://raw.githubusercontent.com/XUNRANA/LNU-LibSeat-Automation/master/docs/screenshots/email_notification.png" width="320" alt="邮件通知">
</p>

---

## 📖 新手小白必读！（保姆级教程）

打开软件后，你需要正确填写以下信息才能顺利抢座：

- 🎯 **目标配置**：选好你想去的校区和自习室，并填上最多十个你最心仪的座位号（按优先级排列）。**一个都不填也行**，系统会随机扫描该自习室全部座位。
- 👤 **账号时间**：填写你的学号和密码（注意：如果没有修改过，初始密码为 `000000`）。

> ⚠️ **重中之重**：抢座的 "左区间（开始时间）" 你可以填"现在"或者整点（如：`9:00`），但抢座的 **"右区间（结束时间）" 必须填整点**，比如 `15:00`，否则学校系统是不认的！

- 📬 **成功通知**：填写你的邮箱地址，任意邮箱都行（只要邮箱存在，抢座成功就会发通知提醒你）。
- ⚙️ **执行模式**：选择"立即执行"或"定时执行"。
  - **定时执行提醒**：如果设置的预约时间大于当前时间，则认为是今天抢座；如果小于当前时间，则默认是在倒计时等待明天的抢座！
  - **卡点启动说明**：系统会在预约整点前 30 秒自动启动浏览器完成登录和预热，提前 6 秒锁定座位，整点准时点击提交！
- 🔐 **图鉴 API 开关**：开启后全天使用商业级图鉴 API 识别验证码（更高准确率，官方计费），关闭则仅每日 6:30-6:35 高峰期使用。

---

## 🏛️ 辽大图书馆预约规则！

> 为了避免因为一时疏忽被拉进黑名单，抢座成功后请务必遵守学校官方的签到规则：

**一、基本信息**
- 线上登录地址：`libseat.lnu.edu.cn`
- 微信入口：辽宁大学图书馆公众号 → 服务 → 座位预约
- **初始密码**：`000000`（如需修改可能通过校园网至 `opac.lnu.edu.cn` "我的图书馆" 修改）

**二、千万勿触碰的红线红区（核心规则）**
1. ✅ 预约成功后，**必须到馆刷校园卡签到**，一旦未按时签到就会被认为违约！
2. ✅ 签到时间范围：**允许提前 30 分钟签到，最晚不能超过你预约时间之后的 30 分钟**。
3. ✅ 如果遇突发情况不能去：请务必提前登录系统手动**取消预约**。
4. 🚫 **连续或 7 天内累计 3 次违约，系统将自动把你拉入黑名单，停权 7 天！！！**
5. ⏰ 系统每天放座时间：**每日 6:30** 开始放位。
6. 📊 每日最长配额：每日预约最大 3 次，每次选座时间最长跨度只能是 **6 小时**（所以你可以 9:00-15:00 和 15:00-21:00 分两次抢），每天最多只能取消 3 次。

---

## ☕ 赞助支持

> 如果这个项目帮到了你，请考虑请作者喝杯咖啡 ☕ 你的支持是持续维护的最大动力！

<p align="center">
  <img src="https://raw.githubusercontent.com/XUNRANA/LNU-LibSeat-Automation/master/Alipay.jpg" width="250" alt="支付宝赞赏">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <img src="https://raw.githubusercontent.com/XUNRANA/LNU-LibSeat-Automation/master/Wechat%20Pay.png" width="250" alt="微信赞赏">
</p>
<p align="center">
  <b>支付宝</b>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>微信支付</b>
</p>
