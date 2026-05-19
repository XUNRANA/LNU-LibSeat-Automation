"""
SiameseMobileNetV4 孪生网络 — 完全按照作者 (道满PythonAI / yujia) 的原版实现。

backbone: MobileNetV4-Conv-Medium (timm 预训练, 1280 维特征)
fusion:   4 路特征拼接 (v1, v2, |v1-v2|, v1*v2) → 512 → 128 → 1
输入尺寸: 2 × (B, 3, 112, 112)
输出:     (B, 1) logits
"""

import torch
import torch.nn as nn
import timm


class SiameseMobileNetV4(nn.Module):
    """
    MobileNetV4-Conv-Medium 孪生网络，特征维度 1280。
    """

    def __init__(self, pretrained: bool = True) -> None:
        super().__init__()
        self.backbone = timm.create_model(
            "mobilenetv4_conv_medium",
            pretrained=pretrained,
            num_classes=0,
        )
        self.feature_dim = 1280
        self.dropout = nn.Dropout(0.2)

        self.fusion_head = nn.Sequential(
            nn.Linear(self.feature_dim * 4, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(inplace=True),
            nn.Linear(512, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(inplace=True),
            nn.Linear(128, 1),
        )

    def extract_feature(self, x: torch.Tensor) -> torch.Tensor:
        return self.dropout(self.backbone(x))

    def forward(self, x1: torch.Tensor, x2: torch.Tensor) -> torch.Tensor:
        v1 = self.extract_feature(x1)
        v2 = self.extract_feature(x2)
        fused = torch.cat(
            [v1, v2, torch.abs(v1 - v2), v1 * v2],
            dim=1,
        )
        return self.fusion_head(fused)


if __name__ == "__main__":
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("Testing SiameseMobileNetV4...")
    model = SiameseMobileNetV4(pretrained=True).to(device)
    img1 = torch.rand(4, 3, 112, 112, device=device)
    img2 = torch.rand(4, 3, 112, 112, device=device)
    out = model(img1, img2)
    print(f"Output shape: {out.shape}")
    params = sum(p.numel() for p in model.parameters())
    print(f"Total parameters: {params:,}")
