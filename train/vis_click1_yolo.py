"""可视化 click1 YOLO 模型的预测结果。GT=绿色, Pred=红色。"""

from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO


MODEL_PATH = Path("runs/click1/plan_bg_char60_yolov8s_900_100-2/weights/best.pt")
IMAGES_DIR = Path("dataset/click1_yolo_plan_bg_char_60_900_100/images")
LABELS_DIR = Path("dataset/click1_yolo_plan_bg_char_60_900_100/labels")
OUTPUT_DIR = Path("vis_click1_yolo")
CONF = 0.05
IOU = 0.45
IMGSZ = 640


def draw_boxes(image: np.ndarray, label_path: Path, preds, image_w: int, image_h: int) -> np.ndarray:
    vis = image.copy()
    # Draw GT boxes (green)
    if label_path.exists():
        for line in label_path.read_text().strip().splitlines():
            parts = line.split()
            if len(parts) != 5:
                continue
            _, cx, cy, w, h = (float(x) for x in parts)
            x1 = int((cx - w / 2) * image_w)
            y1 = int((cy - h / 2) * image_h)
            x2 = int((cx + w / 2) * image_w)
            y2 = int((cy + h / 2) * image_h)
            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(vis, "GT", (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    # Draw predicted boxes (red)
    if preds.boxes is not None:
        for box in preds.boxes:
            conf = float(box.conf[0])
            x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].cpu().numpy())
            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(vis, f"{conf:.2f}", (x1, y2 + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
    return vis


def main():
    model = YOLO(str(MODEL_PATH))
    OUTPUT_DIR.mkdir(exist_ok=True)

    for split in ("train", "val"):
        img_dir = IMAGES_DIR / split
        lbl_dir = LABELS_DIR / split
        out_dir = OUTPUT_DIR / split
        out_dir.mkdir(exist_ok=True)

        images = sorted(img_dir.glob("*.png"))
        for img_path in images:
            image = cv2.imread(str(img_path))
            if image is None:
                continue
            h, w = image.shape[:2]
            result = model.predict(
                source=image, imgsz=IMGSZ, conf=CONF, iou=IOU, max_det=300, verbose=False
            )[0]
            label_path = lbl_dir / f"{img_path.stem}.txt"
            vis = draw_boxes(image, label_path, result, w, h)
            cv2.imwrite(str(out_dir / img_path.name), vis)

        print(f"{split}: {len(images)} images saved to {out_dir}")

    print(f"Done. Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
