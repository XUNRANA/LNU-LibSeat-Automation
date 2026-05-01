import time
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

        # 点击自习室
        xpath = f'//*[contains(@class, "room-name") and contains(text(), "{room_name}")]'
        room = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", room)
        time.sleep(0.2)
        driver.execute_script("arguments[0].click();", room)

        # 确认加载完成
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, 'seat-name')))
        return True
    except Exception as e:
        logger.error("❌ %s进房失败: %s", tag, e)
        return False