"""
v8 Siamese — 输出 L2 归一化的 embedding，专为 triplet/cosine 排序训练设计。

与 v7 (siamese_model.py) 的区别:
  - 去掉 fusion_head（不做 4 路 concat 二分类）
  - 增加 projection head: 1280 -> 256 -> 128
  - forward(x1, x2) 返回 cosine 相似度 (B,)
  - encode(x) 返回 L2 归一化 embedding (B, 128) 给 triplet loss / 推理用
"""

from __future__ import annotations

import timm
import torch
import torch.nn as nn
import torch.nn.functional as F


class SiameseMobileNetV4Embed(nn.Module):
    def __init__(self, pretrained: bool = True, embed_dim: int = 128) -> None:
        super().__init__()
        self.backbone = timm.create_model(
            "mobilenetv4_conv_medium",
            pretrained=pretrained,
            num_classes=0,
        )
        self.feature_dim = 1280
        self.embed_dim = embed_dim
        self.projection = nn.Sequential(
            nn.Linear(self.feature_dim, 256),
            nn.BatchNorm1d(256),
            nn.ReLU(inplace=True),
            nn.Dropout(0.1),
            nn.Linear(256, embed_dim),
        )

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        feats = self.backbone(x)
        emb = self.projection(feats)
        return F.normalize(emb, p=2, dim=1)

    def forward(self, x1: torch.Tensor, x2: torch.Tensor) -> torch.Tensor:
        e1 = self.encode(x1)
        e2 = self.encode(x2)
        return (e1 * e2).sum(dim=1)


if __name__ == "__main__":
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = SiameseMobileNetV4Embed(pretrained=True).to(device)
    x1 = torch.rand(4, 3, 112, 112, device=device)
    x2 = torch.rand(4, 3, 112, 112, device=device)
    cos = model(x1, x2)
    emb = model.encode(x1)
    print(f"cos shape: {cos.shape}, range: [{cos.min().item():.3f}, {cos.max().item():.3f}]")
    print(f"emb shape: {emb.shape}, l2 norm: {emb.norm(dim=1).mean().item():.4f}")
    print(f"params: {sum(p.numel() for p in model.parameters()):,}")
