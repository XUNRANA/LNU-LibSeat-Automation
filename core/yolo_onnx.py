"""YOLOv8 ONNX 推理工具 — 无 torch/ultralytics 依赖。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort


@dataclass(frozen=True)
class YoloOnnxDetection:
    conf: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0


class YoloOnnxPredictor:
    def __init__(self, onnx_path: str | Path, conf: float = 0.05, iou: float = 0.45, imgsz: int = 640):
        self.onnx_path = Path(onnx_path)
        self.conf = conf
        self.iou = iou
        self.imgsz = imgsz
        self._session: ort.InferenceSession | None = None

    def _ensure_session(self) -> ort.InferenceSession:
        if self._session is None:
            if not self.onnx_path.exists():
                raise FileNotFoundError(f"YOLO ONNX not found: {self.onnx_path}")
            self._session = ort.InferenceSession(str(self.onnx_path), providers=["CPUExecutionProvider"])
        return self._session

    def warmup(self) -> None:
        dummy = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
        self.predict(dummy)

    def predict(self, image_bgr: np.ndarray, max_det: int = 300) -> list[YoloOnnxDetection]:
        session = self._ensure_session()
        input_name = session.get_inputs()[0].name

        blob, pad_t, pad_l, scale = self._letterbox(image_bgr)
        blob = blob[np.newaxis].astype(np.float32) / 255.0
        blob = blob.transpose(0, 3, 1, 2)  # (1,H,W,3) -> (1,3,H,W)

        output = session.run(None, {input_name: blob})[0]

        if output.ndim == 3 and output.shape[1] == 5:
            raw = output[0].T
        elif output.ndim == 3:
            raw = output[0]
        else:
            raw = output

        detections: list[YoloOnnxDetection] = []
        for det in raw:
            obj_conf = float(det[4])
            if obj_conf < self.conf:
                continue
            cx, cy, w, h = det[:4]
            x1 = (cx - w / 2 - pad_l) / scale
            y1 = (cy - h / 2 - pad_t) / scale
            x2 = (cx + w / 2 - pad_l) / scale
            y2 = (cy + h / 2 - pad_t) / scale
            detections.append(YoloOnnxDetection(obj_conf, x1, y1, x2, y2))

        detections = self._nms(detections, self.iou)
        detections.sort(key=lambda d: d.conf, reverse=True)
        return detections[:max_det]

    def _letterbox(self, image_bgr: np.ndarray) -> tuple[np.ndarray, int, int, float]:
        h, w = image_bgr.shape[:2]
        s = self.imgsz
        scale = min(s / w, s / h)
        nw, nh = int(w * scale), int(h * scale)
        resized = cv2.resize(image_bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((s, s, 3), 114, dtype=np.uint8)
        pad_t = (s - nh) // 2
        pad_l = (s - nw) // 2
        canvas[pad_t : pad_t + nh, pad_l : pad_l + nw] = resized
        return canvas, pad_t, pad_l, scale

    @staticmethod
    def _nms(dets: list[YoloOnnxDetection], iou_threshold: float) -> list[YoloOnnxDetection]:
        if not dets:
            return []
        dets.sort(key=lambda d: d.conf, reverse=True)
        keep: list[YoloOnnxDetection] = []
        while dets:
            best = dets.pop(0)
            keep.append(best)
            dets = [d for d in dets if _iou(best, d) < iou_threshold]
        return keep


def _iou(a: YoloOnnxDetection, b: YoloOnnxDetection) -> float:
    x1 = max(a.x1, b.x1)
    y1 = max(a.y1, b.y1)
    x2 = min(a.x2, b.x2)
    y2 = min(a.y2, b.y2)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (a.x2 - a.x1) * (a.y2 - a.y1)
    area_b = (b.x2 - b.x1) * (b.y2 - b.y1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0
