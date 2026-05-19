"""
Click1 YOLO4 + Siamese 验证码求解器。

1 个 plan 裁剪 × 4 个 YOLO 候选 → Siamese argmax → 1 个坐标。
端到端准确率 83.48%，YOLO 覆盖率 100%。

用法:
    from core.captcha_click1_yolo4_siamese import solve_click1_target_bg, preload_click1_target_bg
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image

from core.yolo_onnx import YoloOnnxPredictor


@dataclass(frozen=True)
class Click1Detection:
    conf: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0


@dataclass(frozen=True)
class Click1SiameseResult:
    point: tuple[int, int]
    candidates: list[tuple[int, int]]
    candidate_confidences: list[float]
    similarity: list[float]
    best_index: int


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_path(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else _project_root() / p


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _crop_with_padding(
    image: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    fill: tuple[int, int, int],
) -> np.ndarray:
    h, w = image.shape[:2]
    canvas = np.full((max(1, y2 - y1), max(1, x2 - x1), 3), fill, dtype=np.uint8)
    sx1, sy1 = max(0, x1), max(0, y1)
    sx2, sy2 = min(w, x2), min(h, y2)
    if sx2 > sx1 and sy2 > sy1:
        canvas[sy1 - y1 : sy2 - y1, sx1 - x1 : sx2 - x1] = image[sy1:sy2, sx1:sx2]
    return canvas


def _preprocess_siamese(image_bgr: np.ndarray, input_size: tuple[int, int] = (112, 112)) -> np.ndarray:
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    h, w = input_size
    ih, iw = rgb.shape[:2]
    scale = min(w / iw, h / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    resized = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_CUBIC)
    canvas = np.full((h, w, 3), 128, dtype=np.uint8)
    dx, dy = (w - nw) // 2, (h - nh) // 2
    canvas[dy : dy + nh, dx : dx + nw] = resized
    arr = canvas.astype(np.float32) / 255.0
    return np.transpose(arr, (2, 0, 1))


class Click1Yolo4SiameseSolver:
    """End-to-end click1 solver: target+bg -> YOLO four candidates -> Siamese argmax -> 1 point."""

    def __init__(
        self,
        yolo_path: str | Path | None = None,
        siamese_path: str | Path | None = None,
        yolo_imgsz: int = 640,
        yolo_conf: float = 0.05,
        yolo_iou: float = 0.7,
        yolo_device: str = "cpu",
        siamese_device: str = "cpu",
        top_k: int = 4,
        char_crop_size: int = 60,
        plan_left: int = 25,
        plan_right: int = 45,
        plan_top: int = 5,
        plan_bottom: int = 27,
        plan_slot_height: int = 44,
    ) -> None:
        if yolo_path is None:
            yolo_path = "core/checkpoints/click1_yolo_plan_bg_char40_best.onnx"
        if siamese_path is None:
            siamese_path = "core/checkpoints/click1_siamese_yolo4_best.onnx"

        self.yolo_path = _resolve_path(yolo_path)
        self.siamese_path = _resolve_path(siamese_path)
        self.yolo_imgsz = int(yolo_imgsz)
        self.yolo_conf = float(yolo_conf)
        self.yolo_iou = float(yolo_iou)
        self.top_k = int(top_k)
        self.char_crop_size = int(char_crop_size)
        self.plan_left = int(plan_left)
        self.plan_right = int(plan_right)
        self.plan_top = int(plan_top)
        self.plan_bottom = int(plan_bottom)
        self.plan_slot_height = int(plan_slot_height)

        self._yolo: YoloOnnxPredictor | None = None
        self._siamese_ort: ort.InferenceSession | None = None

    def _ensure_yolo(self) -> YoloOnnxPredictor:
        if self._yolo is None:
            self._yolo = YoloOnnxPredictor(
                self.yolo_path, conf=self.yolo_conf, iou=self.yolo_iou, imgsz=self.yolo_imgsz,
            )
        return self._yolo

    def _ensure_siamese_ort(self) -> ort.InferenceSession:
        if self._siamese_ort is None:
            if not self.siamese_path.exists():
                raise FileNotFoundError(f"Siamese ONNX not found: {self.siamese_path}")
            if self.siamese_path.suffix.lower() != ".onnx":
                raise ValueError(f"Production Siamese model must be ONNX: {self.siamese_path}")
            self._siamese_ort = ort.InferenceSession(str(self.siamese_path), providers=["CPUExecutionProvider"])
        return self._siamese_ort

    def warmup(self) -> None:
        self._ensure_yolo()
        self._ensure_siamese_ort()
        plan_crop = np.full(
            (max(1, self.plan_bottom - self.plan_top), max(1, self.plan_right - self.plan_left), 3),
            255,
            dtype=np.uint8,
        )
        bg_bgr = np.full((120, 300, 3), 255, dtype=np.uint8)
        composed = self._compose_plan_bg(plan_crop, bg_bgr)
        self._ensure_yolo().predict(composed, max_det=1)
        char_crops = [
            np.full((self.char_crop_size, self.char_crop_size, 3), 128, dtype=np.uint8)
            for _ in range(4)
        ]
        self._score_siamese(plan_crop, char_crops)

    def _extract_plan_crop(self, target_bgr: np.ndarray) -> np.ndarray:
        return _crop_with_padding(
            target_bgr,
            self.plan_left,
            self.plan_top,
            self.plan_right,
            self.plan_bottom,
            fill=(255, 255, 255),
        )

    def _compose_plan_bg(self, plan_crop: np.ndarray, bg_bgr: np.ndarray) -> np.ndarray:
        bg_h, bg_w = bg_bgr.shape[:2]
        canvas = np.full((self.plan_slot_height + bg_h, bg_w, 3), 255, dtype=np.uint8)
        ch, cw = plan_crop.shape[:2]
        x = (bg_w - cw) // 2
        y = (self.plan_slot_height - ch) // 2
        canvas[y : y + ch, x : x + cw] = plan_crop
        canvas[self.plan_slot_height : self.plan_slot_height + bg_h, 0:bg_w] = bg_bgr
        return canvas

    def _detect_candidates(self, composed_bgr: np.ndarray) -> list[Click1Detection]:
        model = self._ensure_yolo()
        raw = model.predict(composed_bgr, max_det=300)
        detections: list[Click1Detection] = []
        image_h, image_w = composed_bgr.shape[:2]
        for det in raw:
            cx = (det.x1 + det.x2) / 2.0
            cy = (det.y1 + det.y2) / 2.0
            if 0 <= cx <= image_w and self.plan_slot_height <= cy <= image_h:
                detections.append(Click1Detection(det.conf, det.x1, det.y1, det.x2, det.y2))
        return detections[: self.top_k]

    def _score_siamese(self, plan_crop: np.ndarray, char_crops: list[np.ndarray]) -> np.ndarray:
        x1_list: list[np.ndarray] = []
        x2_list: list[np.ndarray] = []
        for char in char_crops:
            # Training order is char first, plan second.
            x1_list.append(_preprocess_siamese(char))
            x2_list.append(_preprocess_siamese(plan_crop))
        x1 = np.stack(x1_list, axis=0).astype(np.float32)
        x2 = np.stack(x2_list, axis=0).astype(np.float32)

        session = self._ensure_siamese_ort()
        inputs = [inp.name for inp in session.get_inputs()]
        output = session.get_outputs()[0].name
        logits = session.run([output], {inputs[0]: x1, inputs[1]: x2})[0]
        return _sigmoid(logits.reshape(-1))

    @staticmethod
    def _image_bytes_to_bgr(image_bytes: bytes) -> np.ndarray:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

    def solve(
        self,
        target_bytes: bytes,
        bg_bytes: bytes,
        return_details: bool = False,
    ) -> tuple[int, int] | Click1SiameseResult | None:
        target_bgr = self._image_bytes_to_bgr(target_bytes)
        bg_bgr = self._image_bytes_to_bgr(bg_bytes)
        return self.solve_arrays(target_bgr, bg_bgr, return_details=return_details)

    def solve_arrays(
        self,
        target_bgr: np.ndarray,
        bg_bgr: np.ndarray,
        return_details: bool = False,
    ) -> tuple[int, int] | Click1SiameseResult | None:
        plan_crop = self._extract_plan_crop(target_bgr)
        composed = self._compose_plan_bg(plan_crop, bg_bgr)
        detections = self._detect_candidates(composed)
        # Production rule: YOLO must provide exactly four retained candidates.
        # Anything else is treated as an unusable captcha and the caller refreshes.
        if len(detections) != 4:
            return None

        half = self.char_crop_size // 2
        char_crops: list[np.ndarray] = []
        centers: list[tuple[int, int]] = []
        for det in detections:
            cx, cy = det.center
            bx = int(round(cx))
            by = int(round(cy - self.plan_slot_height))
            crop = _crop_with_padding(bg_bgr, bx - half, by - half, bx + half, by + half, fill=(128, 128, 128))
            char_crops.append(crop)
            centers.append((bx, by))

        sim = self._score_siamese(plan_crop, char_crops)
        best_idx = int(np.argmax(sim))
        point = centers[best_idx]

        if not return_details:
            return point
        return Click1SiameseResult(
            point=point,
            candidates=centers,
            candidate_confidences=[det.conf for det in detections],
            similarity=sim.tolist(),
            best_index=best_idx,
        )


_solver: Click1Yolo4SiameseSolver | None = None


def get_click1_yolo4_siamese_solver(**kwargs: Any) -> Click1Yolo4SiameseSolver:
    global _solver
    if _solver is None or kwargs:
        _solver = Click1Yolo4SiameseSolver(**kwargs)
    return _solver


def solve_click1_target_bg(target_bytes: bytes, bg_bytes: bytes) -> tuple[int, int] | bool:
    """Local captcha API: target+bg bytes -> one bg coordinate, or False."""
    point = get_click1_yolo4_siamese_solver().solve(target_bytes, bg_bytes)
    if point is None:
        return False
    return (int(point[0]), int(point[1]))


def preload_click1_target_bg() -> None:
    """Load and warm the production YOLO4+Siamese click1 captcha solver before rush time."""
    get_click1_yolo4_siamese_solver().warmup()
