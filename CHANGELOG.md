# 更新日志

本文件记录项目的重要变更，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

各大版本的完整说明见 [`docs/RELEASE_NOTES_V5.md`](docs/RELEASE_NOTES_V5.md)（v5）与 [`docs/RELEASE_NOTES.md`](docs/RELEASE_NOTES.md)（v3）。

## [Unreleased]

### Added
- CI 工作流（`.github/workflows/ci.yml`）：push / PR 上跑 `pytest` + `ruff`。
- 项目文档：`CONTRIBUTING.md`、`SECURITY.md`、`CHANGELOG.md`、`.github` issue/PR 模板，以及 `core/`、`logic/`、`ui_qt/`、`model/`、`tests/`、`info/` 各模块 README。
- `pytest.ini`：注册 `smoke` marker（标记需真实浏览器的端到端用例）。

### Changed
- 测试套件对齐重构后的现存 API（`tests/test_schedule_logic.py` 改测 `build_custom_schedule`）。
- 全仓异常捕获按域收窄（selenium → `WebDriverException`、文件/进程 → `OSError`、解码 → `ValueError` 等），仅在模型黑盒/方法级兜底/日志健壮性处保留宽 `except`；行为等价。
- README 补 CI 徽章、测试跑法与项目结构说明。

### Removed
- 清理 5 处未用导入（ruff F401）。
- 删除测试已淘汰 OCR 点选 API 的 `tests/test_click_captcha_solver.py`。

## [5.0.0]
- 全新 PySide6 界面；自研 **YOLOv8 + Siamese** 本地验证码识别取代付费 API；模型预加载；全自习室扫描；会话级追溯（日志 + 截图 + 录屏）。
- 详见 [`docs/RELEASE_NOTES_V5.md`](docs/RELEASE_NOTES_V5.md) 与 [`docs/MIGRATION_V3_TO_V5.md`](docs/MIGRATION_V3_TO_V5.md)。

## [3.0.1]
- v3 维护修复。

## [3.0.0]
- 整间自习室兜底扫描、双引擎验证码（图鉴 API + ddddocr）、会话级追踪。详见 [`docs/RELEASE_NOTES.md`](docs/RELEASE_NOTES.md)。

## [2.3.0] – [2.8.0]
- 早期迭代：点选文字验证码识别、多账号并发、定时模式等逐步成型（见 git 标签）。

[Unreleased]: https://github.com/XUNRANA/LNU-LibSeat-Automation/compare/v5.0.0...HEAD
[5.0.0]: https://github.com/XUNRANA/LNU-LibSeat-Automation/releases/tag/v5.0.0
[3.0.1]: https://github.com/XUNRANA/LNU-LibSeat-Automation/releases/tag/v3.0.1
[3.0.0]: https://github.com/XUNRANA/LNU-LibSeat-Automation/releases/tag/v3.0.0
