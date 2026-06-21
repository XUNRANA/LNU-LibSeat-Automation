# 贡献指南

感谢你愿意为 **LNU-LibSeat-Automation** 出一份力！本文档说明如何从源码运行、开发规范与提交流程。

> 普通用户无需阅读本文档——直接到 [Releases](https://github.com/XUNRANA/LNU-LibSeat-Automation/releases/latest) 下载开箱即用的 exe / app 即可。本文档面向开发者。

## 环境准备

- Python 3.12（CI 基准；3.8+ 一般可用）
- Windows 装 Edge 或 Chrome；macOS 装 Chrome

```powershell
git clone https://github.com/XUNRANA/LNU-LibSeat-Automation
cd LNU-LibSeat-Automation
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python gui_qt.py            # GUI 入口
```

`config.py` 由 GUI 首次运行自动生成（含学号/密码，已被 `.gitignore` 忽略，**切勿提交**）；
也可手动从 `config.example.py` 复制。

## 跑测试与 lint

CI（`.github/workflows/ci.yml`）在每次 push / PR 上跑下面两项，提交前请本地先过：

```powershell
pip install pytest ruff
pytest -m "not smoke"      # smoke 用例会启动真实浏览器，日常跳过（与 CI 一致）
ruff check .              # 阻塞门槛：全量默认规则集（含 E9/F63/F7/F82 等真 bug 类，与 CI 一致、须 0 告警）
```

- `pytest -m smoke` 可单独跑需要真实浏览器的端到端冒烟用例（本地手动验证用）。
- 改动抢座核心流程（`logic/booker.py`、`logic/auth.py`、`main.py`）后，建议**择日非整点**做一次真机端到端冒烟（登录→进自习室→选座→验证码→提交），机器测试覆盖不到这一层。

## 代码规范

- 异常捕获**按域收窄**：selenium 调用用 `WebDriverException`，文件/进程用 `OSError`，解码用 `ValueError` 等；仅在包裹模型黑盒（onnxruntime/cv2）、方法级兜底边界、日志/GUI 健壮性处才保留宽 `except Exception`，并加注释说明意图。
- 验证码模型对外是 **YOLOv8 + Siamese**；源码里的 `yolo4` 只是内部实验代号，不代表架构版本。
- 类型检查用 `mypy`（CI 非阻塞）。本地 Windows / 旧版 mypy 可能漏报 CI（mypy 2.1.0 / Linux）的告警——改类型后请跑 `mypy --platform linux .` 对齐 CI 视角，并确认输出末行是 `Success`。
- 把超长方法**行为等价拆分**出的 helper，保持与周围方法一致的（通常无）类型标注风格；别只给抽出的 helper 单独加注解，否则会触发额外的 mypy 函数体检查。
- 提交信息用中文、`类型(范围): 摘要` 形式（如 `refactor(booker): ...`、`docs(readme): ...`）。

## 分支与提交

- 主分支 `master`。请基于最新 `master` 开分支，通过 PR 合入。
- 本仓库**只做 forward commit**：不 rebase/amend 旧提交、不 force-push、不重写历史。

## 目录速览

各目录职责见对应 `README.md`：[`core/`](core/README.md) · [`logic/`](logic/README.md) · [`ui_qt/`](ui_qt/README.md) · [`model/`](model/README.md) · [`tests/`](tests/README.md) · [`info/`](info/README.md)。架构全貌见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。
