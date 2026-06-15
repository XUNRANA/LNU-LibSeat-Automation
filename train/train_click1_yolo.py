"""
YOLO 训练 — click1, yolov8s + 200 epoch + 强 augmentation。

基于 train_click3_yolo_v2.py 改造：
  - 数据: dataset/click1_yolo_plan_bg_char_60_900_100/data.yaml
  - 输出: runs/click1/plan_bg_char60_yolov8s_900_100/

用法:
  python train_click1_yolo.py
  python train_click1_yolo.py --epochs 200 --imgsz 640 --batch 8
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _load_class_names(data_path: Path) -> list[str]:
    names: list[str] = []
    in_names = False
    for raw_line in data_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.strip() == "names:":
            in_names = True
            continue
        if not in_names:
            continue
        if not line.startswith(" "):
            break
        if ":" not in line:
            continue
        _idx, name = line.split(":", 1)
        names.append(name.strip().strip("'\""))
    return names


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("dataset/click1_yolo_plan_bg_char_40_900_100/data.yaml"))
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default=None)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--project", type=Path, default=Path("runs/click1"))
    parser.add_argument("--name", default="plan_bg_char40_yolov8n_900_100")
    parser.add_argument("--patience", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--optimizer", default="SGD", help="Optimizer: SGD, Adam, AdamW, auto, etc.")
    parser.add_argument("--lr0", type=float, default=0.005)
    parser.add_argument("--lrf", type=float, default=0.01)
    parser.add_argument("--warmup-epochs", type=float, default=5.0)
    parser.add_argument("--mosaic", type=float, default=1.0)
    parser.add_argument("--copy-paste", type=float, default=0.5)
    parser.add_argument("--erasing", type=float, default=0.0)
    parser.add_argument("--cos-lr", action="store_true", default=True, help="Use cosine LR schedule.")
    parser.add_argument("--no-cos-lr", dest="cos_lr", action="store_false")
    parser.add_argument("--close-mosaic", type=int, default=20, help="Disable mosaic augmentation for the last N epochs.")
    parser.add_argument("--cache", action="store_true")
    parser.add_argument("--exist-ok", action="store_true", default=True)
    parser.add_argument("--export-onnx", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workspace = Path.cwd()
    config_dir = workspace / ".tmp" / "ultralytics"
    config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(config_dir.resolve()))

    data_path = args.data.resolve()
    if not data_path.exists():
        raise SystemExit(f"data yaml not found: {data_path}")

    import torch
    from ultralytics import YOLO

    device = args.device if args.device is not None else (0 if torch.cuda.is_available() else "cpu")

    model = YOLO(args.model)
    train_kwargs = {
        "data": str(data_path),
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "workers": args.workers,
        "device": device,
        "project": str(args.project.resolve()),
        "name": args.name,
        "exist_ok": args.exist_ok,
        "patience": args.patience,
        "seed": args.seed,
        "cache": args.cache,
        "plots": False,
        "val": True,
        "optimizer": args.optimizer,
        "lr0": args.lr0,
        "lrf": args.lrf,
        "warmup_epochs": args.warmup_epochs,
        "mosaic": args.mosaic,
        "copy_paste": args.copy_paste,
        "erasing": args.erasing,
        "cos_lr": args.cos_lr,
        "close_mosaic": args.close_mosaic,
    }

    print(f"device: {device}")
    print(f"data: {data_path}")
    print(f"model: {args.model}, imgsz={args.imgsz}, epochs={args.epochs}, batch={args.batch}")
    results = model.train(**train_kwargs)

    save_dir = Path(getattr(results, "save_dir", model.trainer.save_dir)).resolve()
    best_pt = save_dir / "weights" / "best.pt"
    print(f"save_dir: {save_dir}")
    print(f"best_pt: {best_pt}")

    # 自动测试集评估
    if best_pt.exists():
        trained = YOLO(str(best_pt))
        print("\n=== Test split metrics ===")
        test_metrics = trained.val(
            data=str(data_path),
            split="test",
            imgsz=args.imgsz,
            batch=args.batch,
            device=device,
            plots=False,
        )
        try:
            print(f"test mAP50: {test_metrics.box.map50:.4f}")
            print(f"test mAP50-95: {test_metrics.box.map:.4f}")
            if hasattr(test_metrics.box, "maps"):
                names = _load_class_names(data_path)
                for i, m in enumerate(test_metrics.box.maps[: len(names)]):
                    label = names[i] if i < len(names) else str(i)
                    print(f"  {label} mAP50-95: {float(m):.4f}")
        except Exception as exc:
            print(f"(failed to print summary: {exc})")

        if args.export_onnx:
            exported = trained.export(format="onnx", imgsz=args.imgsz, dynamic=True, simplify=False, opset=12)
            print(f"onnx: {exported}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
