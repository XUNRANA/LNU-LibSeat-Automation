# model/ — Siamese 模型定义（训练用）

验证码识别中 Siamese 相似度网络的**模型定义与数据加载**，供训练/重训使用。

| 文件 | 职责 |
|------|------|
| `siamese_model.py` | Siamese 网络结构（MobileNetV4-Conv-Medium 骨干 + 自定义融合头） |
| `siamese_dataloader.py` | 训练数据加载（plan + bg 合成图范式） |

> **运行时不需要本目录**：抢座时加载的是 [`core/checkpoints/`](../core/README.md) 下导出的 ONNX 权重。
> 训练脚本、超参与评测在 `train/`（见 `train/README.md`）。
> 模型整体设计见 [`docs/CAPTCHA_YOLO4_SIAMESE.md`](../docs/CAPTCHA_YOLO4_SIAMESE.md)。
