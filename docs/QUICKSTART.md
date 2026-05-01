# ⚡ 快速上手教程

## 📋 电脑环境要求

1. **💻 操作系统**：Windows 10 / 11。
2. **🌐 浏览器**：已安装 Microsoft Edge 或 Google Chrome（较新版本即可）。
3. **📶 网络**：能正常打开"辽宁大学座位预约系统"。

> ❌ **不需要** Python、环境变量、代码编辑器、手动下载驱动。

---

## 方式一：下载 EXE（推荐零基础用户）

### Step 1：下载

前往 [Releases](https://github.com/XUNRANA/LNU-LibSeat-Automation/releases/latest) 下载 `LNU-LibSeat-v3.0.0.zip`，解压。

### Step 2：运行

双击 `LNU-LibSeat.exe`。

### Step 3：配置

1. **目标设置**：选校区、自习室，填最多 10 个首选座位号。**不填也可**，系统自动扫描全自习室。
2. **账号信息**：学号 + 密码；双账号可启用副账号分时段。
3. **图鉴 API**：可选开关，开启后全天使用商业 API（更准），关闭仅高峰期 API。
4. **成功通知**：填写接收邮箱（可选）。
5. **执行模式**：立即 / 定时。

### Step 4：开始

点击「🚀 开始抢座」。

---

## 方式二：Python 源码运行

```powershell
git clone https://github.com/XUNRANA/LNU-LibSeat-Automation
cd LNU-LibSeat-Automation
```
双击 `run.bat` 或 `python gui.py`。

---

## 🔧 常见问题 FAQ

### Q: 浏览器报错 "driver not found"？
**A**: 确保网络畅通。可手动下载驱动并在 `config.py` 配置 `DRIVER_PATH`。

### Q: 验证码一直失败？
**A**: 开启「图鉴API抢座」开关，商业 API 准确率更高。本地 OCR 平均 1.3 次识别成功，78% 一把过。

### Q: 抢座失败了怎么排查？
**A**: 查看 `logs/sessions/<时间戳>_<账号>/` 文件夹：
- `session.log` — 完整日志
- `抢座顺序.txt` — 座位顺序
- `*_1_captcha_popup_*.png` — 验证码弹窗截图
- `*_2_text_clicked_*.png` — 点击文字后截图
- `*_3_confirm_clicked_*.png` — 点击确定后截图
- `*_4_result_*.png` — 结果截图
- `recordings/*.mp4` — 录屏视频

### Q: 电脑会休眠吗？
**A**: 不会。程序自动申请系统唤醒权限，支持 10 小时以上挂机。

### Q: 怎么做到每天自动运行？
**A**: Windows 任务计划程序，触发器设每天凌晨 `00:15`，操作选 `LNU-LibSeat.exe`，勾选"唤醒计算机"。

---

## 下一步

- 📖 [配置详解](CONFIGURATION.md)
- 🏗️ [架构文档](ARCHITECTURE.md)
