"""Siamese 验证码模型定义与训练数据加载器（离线训练用，运行时不需要）。

运行时验证码识别走 ONNX（`core/captcha_*_yolo4_siamese.py` + `core/yolo_onnx.py`），
不依赖本包。本包仅供训练 / 复现：`train/` 下脚本通过
`from model.siamese_model import ...` / `from model.siamese_dataloader import ...` 引用。
"""
