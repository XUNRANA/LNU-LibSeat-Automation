# 安全说明

## 报告漏洞

如发现安全问题，请通过 [GitHub Issues](https://github.com/XUNRANA/LNU-LibSeat-Automation/issues) 反馈。
若涉及敏感信息（如可泄露他人凭据的问题），请在标题注明「安全」并**避免在正文公开复现细节**，等作者回应后再私下提供。

## 使用者须知（敏感数据）

- **`config.py` 含明文学号 / 密码**。该文件已被 `.gitignore` 忽略，**绝不要提交到 git、不要随截图/日志外发**。模板见 `config.example.py`。
- 抢座日志、会话录屏、截图（`logs/`）可能包含你的账号界面信息，分享排查文件前请自行确认无敏感内容。
- 邮件通知功能需要 SMTP 凭据：推荐在 `config.py` 用 `SMTP_USER` / `SMTP_PASS` 填**你自己的**发件邮箱授权码，而不是依赖内置默认值。

## 已知限制

- 仓库源码中的发件邮箱 SMTP 凭据为内置默认值，属已知限制；从源码运行并启用邮件通知的用户应以自己的凭据覆盖。
- 本项目仅供技术学习与交流，请遵守辽宁大学图书馆的预约规则；所有使用后果由使用者自行承担（详见 [README 免责声明](README.md#-免责声明)）。

## 支持范围

仅对最新发布版本（见 [Releases](https://github.com/XUNRANA/LNU-LibSeat-Automation/releases/latest) 与 [CHANGELOG](CHANGELOG.md)）提供安全修复。
