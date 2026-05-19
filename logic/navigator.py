import time
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from core.logger import get_logger

logger = get_logger(__name__)


def enter_room(driver, campus_name, room_name, account: str = ""):
    """进入指定的校区及自习室。account 仅用于日志路由（按账号拆分日志文件）。"""
    tag = f"[{account}] " if account else ""
    logger.info("🏫 %s正在进入: %s -> %s", tag, campus_name, room_name)
    wait = WebDriverWait(driver, 10)
    try:
        try:
            driver.find_element(By.CSS_SELECTOR, ".el-select__caret").click()
            wait.until(EC.element_to_be_clickable((By.XPATH, f"//li/span[text()='{campus_name}']"))).click()
            time.sleep(0.5)
        except Exception as e:
            logger.debug("%s切换校区失败或无需切换: %s", tag, e)

        # 点击自习室（页面可能自动刷新导致元素失效，重试最多 3 次）
        xpath = f'//*[contains(@class, "room-name") and contains(text(), "{room_name}")]'
        for _attempt in range(3):
            try:
                room = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", room)
                time.sleep(0.2)
                driver.execute_script("arguments[0].click();", room)
                break
            except StaleElementReferenceException:
                logger.debug("%s自习室元素失效（页面可能刷新），重试...", tag)
                time.sleep(0.5)
            except Exception as e:
                logger.warning("%s点击自习室异常（第 %d 次），重试: %s", tag, _attempt + 1, e)
                time.sleep(1)
        else:
            logger.error("❌ %s点击自习室连续 3 次失败，放弃", tag)
            return False

        # 确认加载完成
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, 'seat-name')))
        return True
    except Exception as e:
        logger.error("❌ %s进房失败: %s", tag, e)
        return False