"""
Gemini 2.5 Flash 验证码识别 API 客户端。

用大模型视觉能力识别点选验证码中的文字位置，返回精确像素坐标。
作为图鉴 (TTShiTu) API 的替代方案，免费额度大，准确率高。
"""
import base64
import json
import re
from io import BytesIO

import requests
from PIL import Image

from core.logger import get_logger

logger = get_logger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_TIMEOUT = 30

PROMPT_TEMPLATE = """你是一个点选验证码识别专家。

第一张图片是【提示图】，显示了需要按顺序点击的目标汉字。
第二张图片是【背景图】（尺寸 {width}×{height} 像素），上面散落着多个汉字。

任务：
1. 从提示图中识别需要依次点击的目标汉字
2. 在背景图中精确定位每个目标汉字的中心位置
3. 按照提示图要求的顺序，返回每个汉字在背景图中的像素坐标

严格按以下 JSON 格式返回，不要包含任何其他文字或 markdown 标记：
[{"char":"字","x":123,"y":456}]

注意：
- x,y 是该汉字在背景图中的中心像素坐标
- x 范围 [0, {width}]，y 范围 [0, {height}]
- 必须按提示图中要求的顺序排列
- 只返回 JSON，不要有任何解释"""


class GeminiCaptchaSolver:
    """Gemini 2.5 Flash 点选验证码求解器。"""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.api_key = api_key
        self.model = model

    def solve_click_captcha(self, prompt_bytes: bytes, bg_bytes: bytes):
        """
        识别点选验证码。

        Args:
            prompt_bytes: 目标文字图(.captcha-modal-click img.captcha-text)的原始 bytes
            bg_bytes:     点击大图(.captcha-modal-content img)的原始 bytes

        Returns:
            dict {
                "success": bool,
                "click_points_in_bg": [(x_in_bg_image, y_in_bg_image), ...]  # 实际像素
                "bg_pil": PIL.Image,
                "id": str (Gemini 无退费机制，始终为空),
                "error": str (失败时)
            }
        """
        bg_pil = Image.open(BytesIO(bg_bytes))
        bg_w, bg_h = bg_pil.size

        # 检测图片 MIME 类型
        prompt_mime = self._detect_mime(prompt_bytes)
        bg_mime = self._detect_mime(bg_bytes)

        prompt_b64 = base64.b64encode(prompt_bytes).decode()
        bg_b64 = base64.b64encode(bg_bytes).decode()

        text_prompt = PROMPT_TEMPLATE.format(width=bg_w, height=bg_h)

        payload = {
            "contents": [{
                "parts": [
                    {"text": text_prompt},
                    {"inline_data": {"mime_type": prompt_mime, "data": prompt_b64}},
                    {"inline_data": {"mime_type": bg_mime, "data": bg_b64}},
                ]
            }],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 512,
            }
        }

        url = f"{GEMINI_API_BASE}/models/{self.model}:generateContent?key={self.api_key}"

        try:
            resp = requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
            result = resp.json()
        except Exception as e:
            logger.warning("⚠️ Gemini 请求异常: %s", e)
            return {"success": False, "error": f"Gemini 请求异常: {e}"}

        # 检查 API 级别错误
        if "error" in result:
            err_msg = result["error"].get("message", str(result["error"]))
            logger.warning("⚠️ Gemini API 错误: %s", err_msg)
            return {"success": False, "error": f"Gemini API 错误: {err_msg}"}

        # 解析响应
        try:
            candidates = result.get("candidates", [])
            if not candidates:
                return {"success": False, "error": "Gemini 无候选结果"}

            # 提取文本部分（跳过 thinking 部分）
            text = self._extract_text(candidates[0])
            if not text:
                return {"success": False, "error": "Gemini 响应中无文本内容"}

            logger.info("🤖 Gemini 原始响应: %s", text.strip()[:300])

            # 解析坐标
            coords = self._parse_coords(text, bg_w, bg_h)
            if not coords:
                return {"success": False, "error": f"无法解析坐标: {text[:200]}"}

            logger.info("✅ Gemini 求解完成，%d 个点击点: %s", len(coords), coords)

            return {
                "success": True,
                "click_points_in_bg": coords,
                "bg_pil": bg_pil,
                "id": "",  # Gemini 没有退费机制
            }
        except Exception as e:
            logger.warning("⚠️ Gemini 解析异常: %s", e)
            return {"success": False, "error": f"Gemini 解析异常: {e}"}

    @staticmethod
    def _detect_mime(img_bytes: bytes) -> str:
        """根据文件头检测图片 MIME 类型。"""
        if img_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        if img_bytes[:2] == b'\xff\xd8':
            return "image/jpeg"
        if img_bytes[:4] == b'RIFF' and img_bytes[8:12] == b'WEBP':
            return "image/webp"
        return "image/png"  # 默认 PNG

    @staticmethod
    def _extract_text(candidate: dict) -> str:
        """从 Gemini 候选响应中提取非 thinking 的文本内容。"""
        parts = candidate.get("content", {}).get("parts", [])
        # Gemini 2.5 可能包含 thought=True 的部分，跳过
        for part in reversed(parts):
            if part.get("thought"):
                continue
            text = part.get("text", "")
            if text.strip():
                return text
        # 兜底：返回最后一个 part 的文本
        if parts:
            return parts[-1].get("text", "")
        return ""

    @staticmethod
    def _parse_coords(text: str, max_w: int, max_h: int):
        """从 Gemini 响应中解析坐标列表。"""
        text = text.strip()
        # 去掉 markdown 代码块标记
        if "```" in text:
            text = re.sub(r"```\w*\n?", "", text).strip()

        # 查找 JSON 数组
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if not match:
            return []

        try:
            items = json.loads(match.group())
        except json.JSONDecodeError:
            logger.warning("⚠️ JSON 解析失败: %s", match.group()[:200])
            return []

        coords = []
        for item in items:
            if not isinstance(item, dict):
                continue
            x = item.get("x")
            y = item.get("y")
            if x is None or y is None:
                continue
            try:
                x = int(float(x))
                y = int(float(y))
            except (ValueError, TypeError):
                continue
            # 裁剪到图片边界内
            x = max(0, min(max_w - 1, x))
            y = max(0, min(max_h - 1, y))
            coords.append((x, y))

        return coords


# --- 单例管理 -----------------------------------------------------------

_solver_singleton = None


def get_solver():
    """懒加载 Gemini 求解器单例（从 config 读取 API Key）。"""
    global _solver_singleton
    if _solver_singleton is not None:
        return _solver_singleton

    try:
        import config as _cfg
        api_key = getattr(_cfg, "GEMINI_API_KEY", "")
    except Exception:
        api_key = ""

    if not api_key:
        logger.info("ℹ️ Gemini API Key 未配置，跳过 Gemini 引擎。")
        return None

    _solver_singleton = GeminiCaptchaSolver(api_key)
    logger.info("✅ Gemini 验证码求解器已初始化 (model=%s)", DEFAULT_MODEL)
    return _solver_singleton
