"""
通义千问 Qwen3-VL 验证码识别 API 客户端。

使用 Qwen3-VL 原生视觉定位能力（bbox_2d，归一化 0-1000 坐标），
精确定位点选验证码中的目标汉字。通过 DashScope OpenAI 兼容接口调用。
"""
import base64
import json
import re
from io import BytesIO

import requests
from PIL import Image

from core.logger import get_logger

logger = get_logger(__name__)

# DashScope OpenAI 兼容接口
API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_MODEL = "qwen3-vl-plus"
DEFAULT_TIMEOUT = 30

PROMPT_TEMPLATE = """你是一个点选验证码识别系统。

## 输入
- 图片1 = 提示条：显示了需要在背景图中点击的目标汉字（1~4个）。
- 图片2 = 背景图：一张风景照片，上面叠加了若干个彩色汉字。

## 任务
1. 从图片1识别所有目标汉字及其顺序
2. 在图片2中定位每个目标汉字
3. 返回每个汉字的 bbox_2d 坐标（归一化 0-1000）

## 输出格式
严格返回 JSON，不要有任何其他文字：
[{"char":"X","bbox_2d":[x1,y1,x2,y2]}]

其中 x1,y1 是左上角，x2,y2 是右下角，范围 0-1000。按顺序排列。"""


class QwenCaptchaSolver:
    """通义千问 Qwen3-VL 点选验证码求解器。"""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.api_key = api_key
        self.model = model

    def solve_click_captcha(self, prompt_bytes: bytes, bg_bytes: bytes):
        """
        识别点选验证码。

        Returns:
            dict {
                "success": bool,
                "click_points_in_bg": [(x, y), ...],
                "bg_pil": PIL.Image,
                "id": "",
                "error": str
            }
        """
        bg_pil = Image.open(BytesIO(bg_bytes))
        bg_w, bg_h = bg_pil.size

        prompt_mime = self._detect_mime(prompt_bytes)
        bg_mime = self._detect_mime(bg_bytes)

        prompt_b64 = base64.b64encode(prompt_bytes).decode()
        bg_b64 = base64.b64encode(bg_bytes).decode()

        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT_TEMPLATE},
                    {"type": "text", "text": "图片1（提示条）："},
                    {"type": "image_url", "image_url": {"url": f"data:{prompt_mime};base64,{prompt_b64}"}},
                    {"type": "text", "text": "图片2（背景图）："},
                    {"type": "image_url", "image_url": {"url": f"data:{bg_mime};base64,{bg_b64}"}},
                ]
            }],
            "temperature": 0,
            "max_tokens": 512,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
            result = resp.json()
        except Exception as e:
            logger.warning("Qwen request error: %s", e)
            return {"success": False, "error": f"Qwen 请求异常: {e}"}

        # 检查错误
        if "error" in result:
            err_msg = result["error"].get("message", str(result["error"]))
            logger.warning("Qwen API error: %s", err_msg)
            return {"success": False, "error": f"Qwen API 错误: {err_msg}"}

        # 解析响应
        try:
            choices = result.get("choices", [])
            if not choices:
                return {"success": False, "error": "Qwen 无返回结果"}

            text = choices[0].get("message", {}).get("content", "")
            if not text:
                return {"success": False, "error": "Qwen 响应为空"}

            # 如果有 thinking 标签，提取最后的内容
            text = self._strip_thinking(text)
            logger.info("Qwen raw: %s", text.strip()[:500])

            coords = self._parse_bbox_coords(text, bg_w, bg_h)
            if not coords:
                return {"success": False, "error": f"无法解析坐标: {text[:200]}"}

            logger.info("Qwen solved: %d points, coords=%s (bg=%dx%d)",
                        len(coords), coords, bg_w, bg_h)

            return {
                "success": True,
                "click_points_in_bg": coords,
                "bg_pil": bg_pil,
                "id": "",
            }
        except Exception as e:
            logger.warning("Qwen parse error: %s", e)
            return {"success": False, "error": f"Qwen 解析异常: {e}"}

    @staticmethod
    def _detect_mime(img_bytes: bytes) -> str:
        if img_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        if img_bytes[:2] == b'\xff\xd8':
            return "image/jpeg"
        if img_bytes[:4] == b'RIFF' and img_bytes[8:12] == b'WEBP':
            return "image/webp"
        return "image/png"

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """去除 Qwen 可能返回的 <think>...</think> 标签。"""
        # 移除 <think>...</think> 块
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        return text.strip()

    @staticmethod
    def _parse_bbox_coords(text: str, bg_w: int, bg_h: int):
        """
        解析 Qwen 返回的 bbox_2d 坐标（归一化 0-1000），转换为像素坐标。

        支持格式：
        - bbox_2d: [{"char":"X", "bbox_2d":[x1,y1,x2,y2]}]
        - cx/cy: [{"char":"X", "cx":500, "cy":300}]
        - x/y: [{"char":"X", "x":500, "y":300}]
        """
        text = text.strip()
        if "```" in text:
            text = re.sub(r"```\w*\n?", "", text).strip()

        match = re.search(r'\[.*\]', text, re.DOTALL)
        if not match:
            return []

        try:
            items = json.loads(match.group())
        except json.JSONDecodeError:
            logger.warning("JSON decode failed: %s", match.group()[:200])
            return []

        coords = []
        for item in items:
            if not isinstance(item, dict):
                continue

            char_name = item.get("char", "?")
            pixel_x, pixel_y = None, None

            # 格式1: bbox_2d [x1, y1, x2, y2] (归一化 0-1000)
            bbox = item.get("bbox_2d") or item.get("bbox") or item.get("box")
            if isinstance(bbox, list) and len(bbox) == 4:
                try:
                    x1, y1, x2, y2 = [float(v) for v in bbox]
                    cx = (x1 + x2) / 2
                    cy = (y1 + y2) / 2
                    pixel_x = cx * bg_w / 1000.0
                    pixel_y = cy * bg_h / 1000.0
                except (ValueError, TypeError):
                    pass

            # 格式2: cx/cy (归一化 0-1000)
            if pixel_x is None and "cx" in item and "cy" in item:
                try:
                    pixel_x = float(item["cx"]) * bg_w / 1000.0
                    pixel_y = float(item["cy"]) * bg_h / 1000.0
                except (ValueError, TypeError):
                    pass

            # 格式3: x/y
            if pixel_x is None and "x" in item and "y" in item:
                try:
                    x_val, y_val = float(item["x"]), float(item["y"])
                    if x_val > bg_w or y_val > bg_h:
                        pixel_x = x_val * bg_w / 1000.0
                        pixel_y = y_val * bg_h / 1000.0
                    else:
                        pixel_x, pixel_y = x_val, y_val
                except (ValueError, TypeError):
                    pass

            if pixel_x is not None and pixel_y is not None:
                px = int(max(0, min(bg_w - 1, pixel_x)))
                py = int(max(0, min(bg_h - 1, pixel_y)))
                logger.info("  -> char='%s' -> pixel=(%d,%d)", char_name, px, py)
                coords.append((px, py))

        return coords


# --- 单例管理 ---

_solver_singleton = None


def get_solver():
    """懒加载 Qwen 求解器单例。"""
    global _solver_singleton
    if _solver_singleton is not None:
        return _solver_singleton

    try:
        import config as _cfg
        api_key = getattr(_cfg, "QWEN_API_KEY", "")
    except Exception:
        api_key = ""

    if not api_key:
        logger.info("Qwen API Key not configured, skipping Qwen engine.")
        return None

    _solver_singleton = QwenCaptchaSolver(api_key)
    logger.info("Qwen captcha solver initialized (model=%s)", DEFAULT_MODEL)
    return _solver_singleton
