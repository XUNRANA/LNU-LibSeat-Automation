# core/ — 基础设施层

与抢座业务无关的底层能力：浏览器驱动、验证码识别、日志、通知、录屏、工具函数。

| 文件 | 职责 |
|------|------|
| `driver.py` | WebDriver 管理（Edge/Chrome），webdriver-manager 下载与缓存回退 |
| `captcha.py` | 登录页 4 位文本验证码（ddddocr），全局单例 `solver` |
| `captcha_yolo4_siamese.py` | 点选验证码 **Click3** 求解器（YOLOv8 检测 + Siamese 相似度） |
| `captcha_click1_yolo4_siamese.py` | 点选验证码 **Click1** 求解器（`Click1Yolo4SiameseSolver.solve()`） |
| `yolo_onnx.py` | ONNX 通用推理封装 |
| `captcha_api.py` | 图鉴（TTShiTu）API 客户端（保留备份，默认不用） |
| `checkpoints/` | 4 个运行时 ONNX 权重（Click1/Click3 的 yolo + siamese） |
| `screen_recorder.py` | 浏览器窗口录屏（Selenium 截图 → OpenCV 写 MP4） |
| `logger.py` | 日志系统（按账号路由、毫秒级时间、GUI 回调 handler） |
| `notifications.py` | SMTP 邮件通知（成功战报） |
| `utils.py` | 时间工具（北京时间等） |
| `paths.py` | 资源路径解析（兼容 PyInstaller 打包后定位） |

> 验证码对外是 **YOLOv8 + Siamese**；文件名里的 `yolo4` 是内部实验代号，非架构版本。
> 训练权重（.pt/.pth）与训练代码不在此处，见 [`model/`](../model/README.md) 与 `train/`。
