import ddddocr
from PIL import Image
from PIL import ImageOps
from io import BytesIO
import base64
import re
from core.logger import get_logger

logger = get_logger(__name__)


class CaptchaSolver:
    def __init__(self):
        # 初始化一次，避免重复加载模型
        self.ocr = ddddocr.DdddOcr(det=False, use_gpu=False, show_ad=False)

    def solve_base64(self, base64_str):
        """解析 Base64 图片流"""
        try:
            image_bytes = base64.b64decode(base64_str)
            image = Image.open(BytesIO(image_bytes))
            return self.ocr.classification(image)
        except Exception as e:
            logger.error("❌ 验证码解析失败: %s", e)
            return ""


class ClickCaptchaSolver:
    """点选文字验证码求解器（预约提交时弹出）"""

    # OCR 常见混淆字（用于轻量容错）
    CHAR_ALIASES = {
        "找": {"这"},
        "这": {"找"},
        "未": {"末"},
        "末": {"未"},
        "土": {"士"},
        "士": {"土"},
        "目": {"日"},
        "日": {"目"},
    }

    def __init__(self):
        self.ocr = ddddocr.DdddOcr(det=False, show_ad=False)
        self.det = ddddocr.DdddOcr(det=True, show_ad=False)

    @staticmethod
    def _is_cjk(ch: str) -> bool:
        return bool(re.match(r"^[\u4e00-\u9fff]$", ch))

    def _extract_target_chars(self, raw_text: str):
        text = (raw_text or "").strip()
        if not text:
            return []

        # 优先提取中文字符（系统点选验证码通常为中文）
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
        if cjk_chars:
            # 若 OCR 带出了提示语，优先取末尾 1~4 字作为目标串
            if len(cjk_chars) > 4:
                cjk_chars = cjk_chars[-4:]
            return cjk_chars

        # 兜底：无中文时按可见字符提取（兼容非常规验证码）
        compact = "".join(ch for ch in text if ch.isalnum())
        if len(compact) > 4:
            compact = compact[-4:]
        return list(compact)

    def _extract_char_candidates(self, crop_img: Image.Image):
        """
        对单个字符区域做多版本 OCR，返回候选字符集合。
        """
        variants = [crop_img, ImageOps.grayscale(crop_img)]
        gray = ImageOps.grayscale(crop_img)
        variants.append(gray.point(lambda p: 255 if p > 150 else 0))

        candidates = []
        raws = []
        seen = set()

        for img in variants:
            buf = BytesIO()
            img.save(buf, format="PNG")
            raw = (self.ocr.classification(buf.getvalue()) or "").strip()
            if raw:
                raws.append(raw)

            cjk_chars = re.findall(r"[\u4e00-\u9fff]", raw)
            if cjk_chars:
                candidate = cjk_chars[0]
            else:
                compact = "".join(ch for ch in raw if ch.isalnum())
                candidate = compact[0] if compact else ""

            if candidate and candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)

        return candidates, raws

    def _chars_match(self, target_char: str, candidate_char: str) -> bool:
        if target_char == candidate_char:
            return True

        # 中文目标优先只匹配中文候选，避免英文噪声干扰
        if self._is_cjk(target_char) and not self._is_cjk(candidate_char):
            return False

        aliases = self.CHAR_ALIASES.get(target_char, set())
        return candidate_char in aliases

    def solve(self, target_bytes, bg_bytes):
        """
        识别点选验证码。

        Args:
            target_bytes: 目标文字图片的原始字节
            bg_bytes:     背景大图的原始字节

        Returns:
            成功: [(x, y), ...] 按点击顺序排列的坐标列表（像素坐标）
            失败: None
        """
        try:
            # 1. 识别目标文字
            target_text_raw = self.ocr.classification(target_bytes)
            target_chars = self._extract_target_chars(target_text_raw)
            logger.info("🔍 点选验证码 — 目标文字原始: %s | 解析后: %s", target_text_raw, "".join(target_chars))
            if not target_chars:
                logger.warning("⚠️ 目标文字识别为空")
                return None
            if len(target_chars) > 4:
                logger.warning("⚠️ 目标文字数量异常: %d（仅支持 1~4）", len(target_chars))
                return None

            # 2. 检测背景图中所有文字区域
            bboxes = self.det.detection(bg_bytes)
            logger.info("🔍 检测到 %d 个文字区域", len(bboxes))
            if not bboxes:
                logger.warning("⚠️ 未检测到任何文字区域")
                return None

            # 3. 逐个裁剪 + OCR 分类
            bg_img = Image.open(BytesIO(bg_bytes))
            char_map = []  # [{"chars": [...], "cx": x, "cy": y}]

            for bbox in bboxes:
                x1, y1, x2, y2 = bbox
                # 稍微扩大裁剪范围提高识别率
                pad = 3
                crop = bg_img.crop((
                    max(0, x1 - pad),
                    max(0, y1 - pad),
                    min(bg_img.width, x2 + pad),
                    min(bg_img.height, y2 + pad),
                ))
                chars, raws = self._extract_char_candidates(crop)
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                logger.info(
                    "  区域 [%d,%d,%d,%d] center=(%d,%d) -> 候选=%s 原始=%s",
                    x1, y1, x2, y2, cx, cy, chars, raws
                )
                if chars:
                    char_map.append({"chars": chars, "cx": cx, "cy": cy})

            # 4. 按目标文字顺序匹配坐标
            click_points = []
            used = set()

            for target_char in target_chars:
                matched = False
                for i, item in enumerate(char_map):
                    if i in used:
                        continue
                    if any(self._chars_match(target_char, char) for char in item["chars"]):
                        click_points.append((item["cx"], item["cy"]))
                        used.add(i)
                        matched = True
                        break
                if not matched:
                    logger.warning("⚠️ 未找到目标文字 '%s' 的匹配项", target_char)
                    return None

            logger.info("✅ 点选验证码求解完成: %s", click_points)
            return click_points

        except Exception as e:
            logger.error("❌ 点选验证码求解异常: %s", e)
            return None


# 单例模式，全局用这就行
solver = CaptchaSolver()
click_solver = ClickCaptchaSolver()
