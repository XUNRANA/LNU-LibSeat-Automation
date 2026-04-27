"""
TTShiTu (图鉴) 验证码识别 API 客户端。

仅在 6:30:00-6:35:00 抢座窗口期使用，提高准确率。
其余时间继续使用本地 ddddocr 模型。
"""
import base64
import time
from io import BytesIO

import requests
from PIL import Image

from core.logger import get_logger

logger = get_logger(__name__)

API_URL = "http://api.ttshitu.com"
DEFAULT_TYPEID = 27  # 点选 1 ~ 4 个坐标
DEFAULT_TIMEOUT = 20


class TTShiTuClient:
    """图鉴 API 点选验证码求解器。"""

    def __init__(self, username: str, password: str, typeid: int = DEFAULT_TYPEID):
        self.username = username
        self.password = password
        self.typeid = typeid

    @staticmethod
    def _combine_prompt_and_bg(prompt_bytes: bytes, bg_bytes: bytes, crop_margin: int = 6):
        """
        把目标文字图与点击大图竖向拼接，再裁去一点点右/下边界。
        返回 (combined_pil, prompt_h)。
        """
        prompt_img = Image.open(BytesIO(prompt_bytes)).convert("RGB")
        bg_img = Image.open(BytesIO(bg_bytes)).convert("RGB")

        max_w = max(prompt_img.width, bg_img.width)
        total_h = prompt_img.height + bg_img.height
        combined = Image.new("RGB", (max_w, total_h), (255, 255, 255))
        combined.paste(prompt_img, (0, 0))
        combined.paste(bg_img, (0, prompt_img.height))

        if crop_margin > 0 and combined.width > crop_margin and combined.height > crop_margin:
            combined = combined.crop(
                (0, 0, combined.width - crop_margin, combined.height - crop_margin)
            )

        return combined, prompt_img.height, bg_img

    @staticmethod
    def _parse_coords(result_str: str):
        """
        把 "x1,y1|x2,y2|x3,y3" 解析成 [(x1,y1), (x2,y2), (x3,y3)]。
        兼容空白与异常字符。
        """
        if not result_str:
            return []
        coords = []
        for chunk in result_str.replace("，", ",").split("|"):
            chunk = chunk.strip()
            if not chunk:
                continue
            parts = chunk.split(",")
            if len(parts) < 2:
                continue
            try:
                x = int(float(parts[0].strip()))
                y = int(float(parts[1].strip()))
                coords.append((x, y))
            except ValueError:
                continue
        return coords

    def _post_predict(self, image_b64: str, remark: str = "", retries: int = 2):
        data = {
            "username": self.username,
            "password": self.password,
            "typeid": str(self.typeid),
            "image": image_b64,
        }
        if remark:
            data["remark"] = remark

        last_msg = ""
        for attempt in range(1, retries + 1):
            try:
                resp = requests.post(
                    f"{API_URL}/predict",
                    json=data,
                    timeout=DEFAULT_TIMEOUT,
                )
                result = resp.json()
            except Exception as e:
                last_msg = f"network: {e}"
                logger.warning("⚠️ TTShiTu 第 %d 次请求异常: %s", attempt, e)
                time.sleep(0.5)
                continue

            if result.get("success"):
                return result.get("data", {})

            last_msg = str(result.get("message", ""))
            logger.warning("⚠️ TTShiTu 第 %d 次返回失败: %s", attempt, last_msg)
            if any(x in last_msg for x in ["人工不足", "超时", "timeout", "请延长超时时间"]):
                time.sleep(0.8)
                continue
            return {"error": last_msg}

        return {"error": last_msg or "TTShiTu 重试仍失败"}

    def solve_click_captcha(self, prompt_bytes: bytes, bg_bytes: bytes, remark: str = ""):
        """
        识别点选验证码。

        Args:
            prompt_bytes: 目标文字图(.captcha-modal-click img.captcha-text)的原始 bytes
            bg_bytes:     点击大图(.captcha-modal-content img)的原始 bytes
            remark:       可选，"按顺序点击X,X,X" 形式的提示。

        Returns:
            dict {
                "success": bool,
                "click_points_in_bg": [(x_in_bg_image, y_in_bg_image), ...]  # 实际像素
                "bg_pil": PIL.Image,
                "id": str (用于报错),
                "error": str (失败时)
            }
        """
        combined, prompt_h, bg_pil = self._combine_prompt_and_bg(prompt_bytes, bg_bytes)
        buf = BytesIO()
        combined.save(buf, format="JPEG", quality=92)
        b64 = base64.b64encode(buf.getvalue()).decode()

        data = self._post_predict(b64, remark=remark)
        if not isinstance(data, dict) or "result" not in data:
            return {"success": False, "error": data.get("error") if isinstance(data, dict) else "unknown"}

        coords = self._parse_coords(data.get("result", ""))
        if not coords:
            return {"success": False, "error": f"无法解析坐标: {data.get('result')}"}

        # 把坐标系从 combined 映射到 bg_pil（减掉 prompt_h）
        bg_w, bg_h = bg_pil.size
        click_points_in_bg = []
        for cx, cy in coords:
            bx = cx
            by = cy - prompt_h
            # 坐标越界则裁剪到 bg 范围内，避免点到提示区
            bx = max(0, min(bg_w - 1, bx))
            by = max(0, min(bg_h - 1, by))
            click_points_in_bg.append((bx, by))

        return {
            "success": True,
            "click_points_in_bg": click_points_in_bg,
            "bg_pil": bg_pil,
            "id": data.get("id", ""),
        }

    def report_error(self, captcha_id: str):
        """识别错误时上报，5 分钟内退还次数。"""
        if not captcha_id:
            return False
        try:
            resp = requests.post(
                f"{API_URL}/reporterror.json",
                json={"id": captcha_id},
                timeout=10,
            )
            return bool(resp.json().get("success"))
        except Exception as e:
            logger.warning("⚠️ TTShiTu 报错接口异常: %s", e)
            return False


# --- 内嵌凭据（已混淆；不在 config 与 GUI 中暴露） -------------------------
# 还原方式: base64 → 反转
_C_U = "YW5hcm51eA=="
_C_P = "dW5MODQ5MQ=="


def _resolve_credentials():
    try:
        u = base64.b64decode(_C_U).decode()[::-1]
        p = base64.b64decode(_C_P).decode()[::-1]
        return u, p
    except Exception:
        return "", ""


_client_singleton = None


def get_client():
    """懒加载图鉴 API 客户端单例（凭据内嵌在本模块底层）。"""
    global _client_singleton
    if _client_singleton is not None:
        return _client_singleton

    username, password = _resolve_credentials()
    if not username or not password:
        logger.info("ℹ️ TTShiTu 凭据不可用，将使用本地 ddddocr 兜底。")
        return None

    _client_singleton = TTShiTuClient(username, password, DEFAULT_TYPEID)
    return _client_singleton
