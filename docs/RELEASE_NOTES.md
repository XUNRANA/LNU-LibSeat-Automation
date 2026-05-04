<div align="center">

# 📦 LNU-LibSeat **v3.0.0**

### 🔥 全自习室扫描时代 · 双引擎 AI · 会话级追溯

**首发 2026-05-04**

[← 返回 README](../README.md) ·
[快速上手](QUICKSTART.md) ·
[配置详解](CONFIGURATION.md) ·
[架构文档](ARCHITECTURE.md)

</div>

---

## 🎯 一句话 

> 以前你只能死磕填进去的座位号，**现在它会替你扫整间自习室**——首选耗尽自动随机摇号，双校区 20 间自习室全覆盖。

---

## 📊 v3.0.0 vs 旧版本一图看懂

| 维度 | 旧版（v2.x） | **v3.0.0** ✨ |
|------|------------|---------------|
| 🎯 座位策略 | 仅按你填的 PREFER_SEATS 顺序死磕 | **首选 + 全房随机兜底** |
| 🤖 验证码引擎 | 仅本地 ddddocr | **API（商业级）+ ddddocr 双引擎** |
| 🎬 抢座过程记录 | 单一日志文件 | **独立目录 + 4 阶段截图 + MP4 录屏** |
| ⏰ 提前锁座 | `fire_at - 2s` | **`fire_at - 6s`**（更稳，避免锁座 3-4s 吃掉触发时机） |
| 🚀 触发时序 | `fire_at` 立即点座位 | **`fire_at + 1s` 才点**（避开服务端切换"放座状态"瞬态空档） |
| ⏲️ 抢座时刻 | 严格 6:30 | **严格 6:30 + 自定义时刻** |
| 🛡️ 黑名单处理 | 继续重试（加重处罚） | **立即停止本次会话** |
| 🔁 验证码重试上限 | 统一 N 次 | **API 5 次 / 本地 OCR 10 次**（差异化） |
| 🪟 浏览器模式 | 支持 headless | **强制可见**（便于监督和复盘） |

---

## 🆕 五大变化 — 你能直接感受到

> [!TIP]
> 下面 5 条是你下载新版后**第一次跑就能感受到**的差异。

### 1. 🎯 不填座位号也能抢

填 0 个首选 → 它会**扫整间自习室全部座位**；填 3 个首选 → 它先死磕这 3 个，失败后**自动兜底扫剩下的**。

> "我也不知道哪个座位好，反正三楼智慧研修空间随便给一个就行" — 这种用户从今天起完美适配。

### 2. 📁 每次抢座都被完整记录

每次会话生成一个独立文件夹：

```
logs/sessions/20260504_062930_2024xxxxxx/
├── session.log         ← 仅本次会话的日志（不再灌历史）
├── 抢座顺序.txt        ← 这次准备试哪些座位、什么顺序
├── 1_185_1_1_captcha_popup_*.png      ← 优先级_座位_重试_阶段_时间戳
├── 1_185_1_2_text_clicked_*.png
├── 1_185_1_3_confirm_clicked_*.png
├── 1_185_1_4_result_failed_*.png
└── recordings/lnu_seat_*.mp4          ← 全程录屏
```

> 出问题了？把这个文件夹打包甩给作者，**比你描述 100 句还清楚**。

### 3. 🛡️ 被拉黑会立刻停

如果你不小心已经被黑名单（违约 3 次），程序检测到提示后**立刻退出当前会话**，避免硬刚把惩罚加重。

之前的版本会继续重试到把 N 个座位都过一遍——这是反作用。

### 4. ⏲️ 可以自定义抢座时刻

不一定 6:30。GUI 里可以填**任意 hh:mm**——以后图书馆要是改放座点，你不用等作者更新版本。

<p align="center">
  <img src="screenshots/gui_scheduled.png" width="520" alt="GUI 自定义抢座时刻">
</p>

### 5. ⚡ 6:30 卡点更稳

触发后**多等 1 秒**再点座位——避开服务端从"未放座"切换到"已放座"的瞬态空档。

实测能多救几个本来会被挤掉的座位。

---

## ⚠️ 升级时要注意

> [!WARNING]
> 从 v2.x 升级到 v3.0.0 时，**请务必看完这一节**。

### 破坏性变更

1. **「后台静默运行」开关已被移除**
   浏览器现在一定会弹出来——这样你能亲眼监督，作者也方便复盘失败 case。

2. **新增「图鉴 API 抢座」开关**
   默认 **关闭**。**强烈建议保持关闭**——它是付费 API（**0.016 元/次**），目前由作者自掏腰包。
   系统已在 6:30-6:35 高峰期**自动**启用 API（5 分钟窗口），其他时段走免费本地 OCR。
   👉 详见 [README §「关于图鉴 API 抢座」](../README.md)

3. **`config.py` 新增字段** `FORCE_API_ALWAYS = False`
   旧 `config.py` 缺这个字段不会报错（缺省为 False），但建议让 GUI 重新生成。

### 推荐升级流程

```powershell
# 1. 备份你的旧 config.py（里面有学号密码）
Copy-Item config.py config.py.bak

# 2. 下载新版 zip 解压到新目录，或：
git pull && python build.py

# 3. 删除旧 dist/ 和旧 config.py
Remove-Item -Recurse dist
Remove-Item config.py

# 4. 双击新版 LNU-LibSeat.exe，GUI 会自动生成新 config.py
```

---

## ☕ 顺便说一句

> [!NOTE]
> 图鉴 API 现在还在**作者钱包里**——每月垫付支撑大家用。
> 如果工具帮到你，**随手扫码**欢迎赞助。❤️
> 
> 👉 二维码在 [README 底部 ☕ 赞助章节](../README.md#-求赞助--让免费持续)

---

## 🔬 技术细节（开发者向）

<details>
<summary><b>📐 核心特性的实现要点</b></summary>

### 全自习室扫描策略

`main.py:run_timed_priority_attack()` 的座位池构建：

1. 加载 `info/<room>.txt` 的座位清单
2. `PREFER_SEATS` 经标准化（去前导零，`001` → `1`）后查表过滤；不存在的首选直接跳
3. 兜底 = `clean(剩余) + random.shuffle()`，写入会话目录的 `抢座顺序.txt`
4. 主循环按"首选有序 + 兜底随机"顺序逐个 `select_time_and_wait`

```python
extended_seats = []                          # 首选标准化后过滤
fallback = [s for s in all_room_seats if s not in tried]
random.shuffle(fallback)                     # 兜底随机洗牌
extended_seats.extend(fallback)
```

### 双引擎验证码 + 双保险点击

- **API 时间窗口** 6:30:00-6:35:00 由 `logic/booker.py:_should_use_api()` 判定
- **`FORCE_API_ALWAYS = True`** 可强制全天走 API
- **ActionChains 真实鼠标事件** 走精确偏移量
- **1.5 秒后按钮仍未渲染** → JS `dispatchEvent` 用精确 CSS 坐标补点
- **Vue 异步状态** 把确认按钮从 `<div class="confirm-btn disabled">` 切换到 `<button class="el-button confirm-btn">` 是异步的——选择器改成 `.el-button.confirm-btn` 才能区分二者
- **错识别自动调图鉴 reporterror** 接口（5 分钟内退还次数）

### 会话级追溯

- 路径：`logs/sessions/<ts>_<account>/`
- `session.log` 通过**文件 offset 截取**实现"仅本次会话"——避免历史日志灌水
- 截图命名规约：`优先级_座位_重试_阶段_时间戳.png`

### 时序参数全表

| 参数 | 值 | 说明 |
|------|-----|------|
| `PREP_LEAD_SECONDS` | **30** | `fire_at` 前多久启动浏览器并登录 |
| `SEAT_LOCK_LEAD_SECONDS` | **6** | `fire_at` 前多久锁定座位（v2.x 是 2，太短） |
| `MAINTENANCE_RETRY_INTERVAL_SECONDS` | **120** | 系统维护时的重试间隔 |
| 触发后 sleep | **1s** | 让服务端切换到"已放座"状态再点 |
| API 重试上限 | **5/座位** | 比本地少（API 慢，避免堆积） |
| 本地 OCR 重试上限 | **10/座位** | 比 API 多（本地快） |
| API 时间窗口 | **06:30:00-06:35:00** | 高峰期强制走 API |

</details>


<details>
<summary><b>📊 验证码识别性能（实测）</b></summary>

> 以下数据来自真实高峰期抢座会话（06:30 放座，244 个座位遍历），分引擎统计。

<table>
  <tr>
    <td valign="top">
      <b>🌐 图鉴 API（商业级，最多 5 次）</b><br><br>
      <table>
        <tr><th>指标</th><th>数值</th></tr>
        <tr><td>识别成功率</td><td><b>100%</b> (14/14)</td></tr>
        <tr><td>最低延迟</td><td><b>3.54s</b></td></tr>
        <tr><td>最高延迟</td><td><b>17.82s</b></td></tr>
        <tr><td>平均延迟</td><td><b>7.21s</b></td></tr>
        <tr><td>中位数延迟</td><td><b>5.96s</b></td></tr>
      </table>
    </td>
    <td valign="top">
      <b>💻 本地 OCR 单次成功率（免费离线）</b><br><br>
      <table>
        <tr><th>指标</th><th>数值</th></tr>
        <tr><td>识别成功率</td><td><b>61.2%</b> (93/152)</td></tr>
        <tr><td>最低延迟</td><td><b>0.32s</b></td></tr>
        <tr><td>最高延迟</td><td><b>0.65s</b></td></tr>
        <tr><td>平均延迟</td><td><b>0.51s</b></td></tr>
        <tr><td>中位数延迟</td><td><b>0.53s</b></td></tr>
      </table>
    </td>
    <td valign="top">
      <b>📈 本地 OCR 累计通过分布（最多 10 次）</b><br><br>
      <table>
        <tr><th>尝试次数</th><th>座位数</th><th>占比</th></tr>
        <tr><td>1 次通过</td><td>69</td><td><b>65.7%</b></td></tr>
        <tr><td>2 次通过</td><td>17</td><td>16.2%</td></tr>
        <tr><td>3 次通过</td><td>14</td><td>13.3%</td></tr>
        <tr><td>4 次通过</td><td>4</td><td>3.8%</td></tr>
        <tr><td>5 次通过</td><td>1</td><td>1.0%</td></tr>
      </table>
    </td>
  </tr>
</table>

**结论**：

- 🎯 图鉴 API **精度极高（100%）**但延迟较大（平均 **7.2s**）——适合极卷的 6:30-6:35 抢座窗口
- ⚡ 本地 OCR **速度快 14 倍**（平均 **0.51s**）但单次 61.2% 成功率较低——失败后会自动刷新重试
- 📊 本地 OCR 累计：**65.7%** 一把过 / **95.2%** 三次内通过 / **100%** 五次内通过
- ✅ 系统默认在 **06:30-06:35** 强制走 API，其他时段走本地 OCR——**这就是为什么 GUI 上那个开关默认是关的**

</details>

<details>
<summary><b>⚠️ 已知限制</b></summary>

- **6:30 高峰极卷**：即使验证码全过，座位仍可能被更快用户抢走
- **图鉴 API 高并发延迟波动大**：3.5s ~ 17.8s 范围内
- **本地 OCR 约 38.8% 概率需重试**：每次重试约浪费 1~2 秒
- **不支持移动端**：仅 Windows 桌面（依赖 Selenium + 桌面浏览器）
- **不支持图书馆系统改版**：每次系统改版都需要适配（XPath/CSS selector 会变）

</details>



<div align="center">

**喜欢这次更新？**

[⭐ Star 一下](https://github.com/XUNRANA/LNU-LibSeat-Automation) · [☕ 赞助一杯奶茶](../README.md#-求赞助--让免费持续) · [🐛 反馈 Bug](https://github.com/XUNRANA/LNU-LibSeat-Automation/issues)

</div>
