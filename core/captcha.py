import ddddocr
from PIL import Image
from io import BytesIO
import base64
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

    def __init__(self):
        self.ocr = ddddocr.DdddOcr(det=False, show_ad=False)
        self.det = ddddocr.DdddOcr(det=True, show_ad=False)

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
            target_text = self.ocr.classification(target_bytes)
            logger.info("🔍 点选验证码 — 目标文字: %s", target_text)
            if not target_text:
                logger.warning("⚠️ 目标文字识别为空")
                return None

            # 2. 检测背景图中所有文字区域
            bboxes = self.det.detection(bg_bytes)
            logger.info("🔍 检测到 %d 个文字区域", len(bboxes))
            if not bboxes:
                logger.warning("⚠️ 未检测到任何文字区域")
                return None

            # 3. 逐个裁剪 + OCR 分类
            bg_img = Image.open(BytesIO(bg_bytes))
            char_map = []  # [(recognized_char, center_x, center_y)]

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
                buf = BytesIO()
                crop.save(buf, format="PNG")
                char = self.ocr.classification(buf.getvalue())
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                logger.info("  区域 [%d,%d,%d,%d] center=(%d,%d) -> '%s'", x1, y1, x2, y2, cx, cy, char)
                if char:
                    char_map.append((char, cx, cy))

            # 4. 按目标文字顺序匹配坐标
            click_points = []
            used = set()

            for target_char in target_text:
                matched = False
                for i, (char, cx, cy) in enumerate(char_map):
                    if i not in used and char == target_char:
                        click_points.append((cx, cy))
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