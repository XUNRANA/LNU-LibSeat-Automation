import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from core.captcha import solver
from core.logger import get_logger

logger = get_logger(__name__)


class Authenticator:
    def __init__(self, driver):
        self.driver = driver
        self.wait = WebDriverWait(driver, 10)

    def login(self, account, password):
        logger.info("👤 [%s] 正在打开登录页...", account)

        try:
            self.driver.get('http://222.26.125.253/libseat/#/login')
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[placeholder="请输入账号"]'))
            )
        except Exception as e:
            logger.warning("⚠️ [%s] 打开网页或等待页面加载超时: %s", account, e)

        logger.info("📄 [%s] 页面标题: 【%s】", account, self.driver.title)

        for i in range(1, 6):
            logger.info("🔄 [%s] 第 %d 次尝试...", account, i)
            try:
                # 1. 填写账号密码
                try:
                    user_input = self.wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'input[placeholder="请输入账号"]'))
                    )
                except Exception:
                    logger.warning("❌ [%s] 找不到输入框，刷新重试...", account)
                    self.driver.refresh()
                    time.sleep(3)
                    continue

                user_input.clear()
                user_input.send_keys(account)
                self.driver.find_element(By.CSS_SELECTOR, 'input[placeholder="请输入密码"]').clear()
                self.driver.find_element(By.CSS_SELECTOR, 'input[placeholder="请输入密码"]').send_keys(password)
                logger.info("📝 [%s] 账号密码已填，正在等验证码...", account)

                # ================= 🔍 核心修改：死等验证码加载 =================
                captcha_base64 = None
                img_element = None

                # 尝试轮询 10 次，每次等 0.5 秒，直到图片 src 有内容
                for _ in range(10):
                    try:
                        img_element = self.driver.find_element(By.CSS_SELECTOR, '.captcha-wrap img')
                        src = img_element.get_attribute("src")
                        if src and "base64" in src:
                            captcha_base64 = src.split(",")[1]
                            break  # 找到了！跳出等待
                        else:
                            # 可能是空的，或者是 loading 图，等待一下
                            time.sleep(0.5)
                    except Exception:
                        time.sleep(0.5)

                if not captcha_base64:
                    logger.warning("⚠️ [%s] 验证码图片加载失败 (src为空)，点击刷新一下...", account)
                    if img_element:
                        img_element.click()  # 点一下也许能刷出来
                    time.sleep(2)
                    continue  # 跳过这次，重试
                # ============================================================

                # 2. 识别并填入
                code = solver.solve_base64(captcha_base64)
                logger.info("🔍 [%s] 验证码识别: %s", account, code)

                if len(code) != 4:
                    logger.warning("⚠️ 验证码长度不对(%s)，刷新...", code)
                    img_element.click()
                    time.sleep(1)
                    continue

                self.driver.find_element(By.CSS_SELECTOR, 'input[placeholder="请输入验证码"]').send_keys(code)

                # 3. 点击登录
                logger.info("🚀 [%s] 点击登录！", account)
                btn = self.driver.find_element(By.XPATH, "//button[contains(@class, 'login-btn')]")
                self.driver.execute_script("arguments[0].click();", btn)

                # 4. 检查结果
                try:
                    # 检测成功跳转
                    WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CLASS_NAME, "header-username"))
                    )
                    logger.info("✅✅✅ [%s] 登录成功！！！", account)
                    return True
                except Exception:
                    # 检测错误提示
                    try:
                        toast = self.driver.find_element(By.CLASS_NAME, "el-message__content")
                        logger.warning("🔔 [%s] 登录失败提示: %s", account, toast.text)
                    except Exception:
                        logger.warning("⚠️ [%s] 点击后无反应，可能验证码错了", account)

            except Exception as e:
                logger.error("❌ [%s] 流程异常: %s", account, e)
                time.sleep(1)

        return False