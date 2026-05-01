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
        self.last_failure_reason = None

    @staticmethod
    def _is_maintenance_notice(text: str) -> bool:
        msg = (text or "").strip()
        return ("系统维护中" in msg) or ("系统维护" in msg)

    @staticmethod
    def _trigger_stop(stop_event):
        if stop_event is None:
            return
        setter = getattr(stop_event, "set", None)
        if callable(setter):
            setter()
            return
        base_event = getattr(stop_event, "base_event", None)
        base_setter = getattr(base_event, "set", None)
        if callable(base_setter):
            base_setter()

    def _handle_maintenance(self, account, notice_text, stop_event, maintenance_mode):
        if maintenance_mode == "defer_until_fire":
            logger.warning(
                "⏸️ [%s] 收到【%s】，当前为预热登录阶段，等待预约时刻再重启浏览器抢座。",
                account,
                notice_text,
            )
            self.last_failure_reason = "maintenance_defer"
            return False
        if maintenance_mode == "retry_later":
            logger.warning(
                "⏳ [%s] 收到【%s】，将在稍后重试启动浏览器。",
                account,
                notice_text,
            )
            self.last_failure_reason = "maintenance_retry_later"
            return False
        logger.error("🛑 [%s] 严重：收到【%s】提示，暂停所有任务！", account, notice_text)
        self._trigger_stop(stop_event)
        self.last_failure_reason = "maintenance_stop"
        return False

    def login(self, account, password, stop_event=None, maintenance_mode="stop"):
        self.last_failure_reason = None
        logger.info("👤 [%s] 正在打开登录页...", account)

        try:
            self.driver.get('http://libseat.lnu.edu.cn/libseat/#/login')
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[placeholder="请输入账号"]'))
            )
        except Exception as e:
            logger.warning("⚠️ [%s] 打开网页或等待页面加载超时: %s", account, e)

        logger.info("📄 [%s] 页面标题: 【%s】", account, self.driver.title)

        # 检查页面是否显示"网络出错了"之类的连接异常
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            if self._is_maintenance_notice(page_text):
                return self._handle_maintenance(account, "系统维护中", stop_event, maintenance_mode)
            if "网络出错" in page_text or "请稍后再试" in page_text:
                logger.warning("🌐 [%s] 页面显示网络异常，等待5秒后刷新...", account)
                time.sleep(5)
                self.driver.refresh()
                time.sleep(3)
        except Exception:
            pass

        for i in range(1, 6):
            if stop_event and stop_event.is_set():
                logger.info("🛑 [%s] 登录中止：收到停止信号", account)
                self.last_failure_reason = "stopped"
                return False
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
                
                pass_input = self.driver.find_element(By.CSS_SELECTOR, 'input[placeholder="请输入密码"]')
                pass_input.clear()
                pass_input.send_keys(password)
                
                logger.info("📝 [%s] 账号密码已填，正在等验证码...", account)

                # ================= 🔍 核心修改：死等验证码加载 =================
                captcha_base64 = None
                img_element = None

                # 尝试轮询 10 次，每次等 0.5 秒，直到图片 src 有内容
                for _ in range(10):
                    if stop_event and stop_event.is_set():
                        return False
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
                    logger.warning("⚠️ [%s] 验证码长度不对(%s)，刷新...", account, code)
                    img_element.click()
                    time.sleep(1)
                    continue

                captcha_input = self.driver.find_element(By.CSS_SELECTOR, 'input[placeholder="请输入验证码"]')
                captcha_input.clear()
                captcha_input.send_keys(code)

                # 3. 提交登录 (恢复为原来的强制点击按钮)
                logger.info("🚀 [%s] 点击登录按钮！", account)
                btn = self.driver.find_element(By.XPATH, "//button[contains(@class, 'login-btn')]")
                self.driver.execute_script("arguments[0].click();", btn)

                # 4. 检查结果 — 让 WebDriverWait 处理跳转等待

                # 4a. 检测是否已成功跳转
                try:
                    WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((By.CLASS_NAME, "header-username"))
                    )
                    logger.info("✅✅✅ [%s] 登录成功！！！", account)
                    return True
                except Exception:
                    pass

                # 4b. 检测页面上的各种错误提示 (Element UI toast / alert)
                error_msg = None
                for selector in [
                    (By.CLASS_NAME, "el-message__content"),
                    (By.CLASS_NAME, "el-message-box__message"),
                    (By.CSS_SELECTOR, ".el-message .el-message__content"),
                    (By.CSS_SELECTOR, ".el-notification__content"),
                ]:
                    try:
                        el = self.driver.find_element(*selector)
                        if el.text.strip():
                            error_msg = el.text.strip()
                            break
                    except Exception:
                        continue

                if error_msg:
                    if self._is_maintenance_notice(error_msg):
                        return self._handle_maintenance(account, error_msg, stop_event, maintenance_mode)
                    
                    logger.warning("🔔 [%s] 登录失败提示: %s", account, error_msg)
                else:
                    logger.warning("⚠️ [%s] 点击后无反应，可能验证码错了", account)

                # 4c. 刷新验证码：点击验证码图片使其重新生成
                try:
                    captcha_img = self.driver.find_element(By.CSS_SELECTOR, '.captcha-wrap img')
                    captcha_img.click()
                    time.sleep(1)
                except Exception:
                    pass

                # 清空验证码输入框，为下次重试做准备
                try:
                    ci = self.driver.find_element(By.CSS_SELECTOR, 'input[placeholder="请输入验证码"]')
                    ci.clear()
                except Exception:
                    pass

            except Exception as e:
                logger.error("❌ [%s] 流程异常: %s", account, e)
                if stop_event and stop_event.is_set():
                    self.last_failure_reason = "stopped"
                    return False
                time.sleep(1)

        if self.last_failure_reason is None:
            self.last_failure_reason = "login_failed"
        return False
