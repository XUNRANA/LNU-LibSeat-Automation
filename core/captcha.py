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

# 单例模式，全局用这就行
solver = CaptchaSolver()