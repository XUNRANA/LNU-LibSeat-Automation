# tests/ — 单元测试

```powershell
pip install pytest
pytest -m "not smoke"      # 日常 / CI：跳过需真实浏览器的用例
pytest -m smoke           # 仅跑端到端冒烟（需装好浏览器，会真打开窗口）
```

| 文件 | 覆盖 |
|------|------|
| `test_schedule_logic.py` | `main.build_custom_schedule` 跨天顺延、lead 常量；`wait_until` 过点立即返回 |
| `test_booker_result_detection.py` | 预约结果文本分类（`logic/result_classifier`） |
| `test_utils.py` | 时间工具函数 |
| `test_driver_unit.py` | driver 选项/构造的纯单元逻辑 |
| `test_driver_smoke.py` | **`@pytest.mark.smoke`** — 真实启动浏览器，CI 跳过 |
| `test_email_manual.py` | 邮件构造（手动/本地） |

> `smoke` marker 在仓库根 [`pyproject.toml`](../pyproject.toml) 注册。CI 配置见 [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)。
> 注意：CI 在 Linux 上无 `config.py`，工作流会先 `cp config.example.py config.py` 再跑测试。
