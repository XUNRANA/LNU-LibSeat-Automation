# logic/booker.py
import os
import time
import random
from datetime import datetime, timezone, timedelta

from selenium.common import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from core.logger import get_logger

logger = get_logger(__name__)


class SeatBooker:
    def __init__(self, driver):
        self.driver = driver
        self.wait = WebDriverWait(driver, 5)

    def _save_failure_screenshot(self, tag="failure"):
        """保存失败截图到 logs 目录，用于事后分析"""
        try:
            log_dir = getattr(__import__("config"), "LOG_DIR", "logs")
            os.makedirs(log_dir, exist_ok=True)
            now = datetime.now(timezone(timedelta(hours=8)))
            filename = f"screenshot_{tag}_{now.strftime('%Y%m%d_%H%M%S')}.png"
            filepath = os.path.join(log_dir, filename)
            self.driver.save_screenshot(filepath)
            logger.info("📸 失败截图已保存: %s", filepath)
        except Exception:
            logger.warning("⚠️ 截图保存失败")

    def click_time_label(self, column_index, time_str, timeout=5):
        """
        辅助函数：点击时间标签 (增加超时参数)
        """
        try:
            # 尝试定位时间标签
            xpath = f'(//div[@class="times-roll"])[{column_index}]//label[contains(text(), "{time_str}")]'
            # 使用传入的 timeout
            label = WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            label.click()
            return True
        except TimeoutException:
            return False
        except NoSuchElementException:
            # 如果元素结构发生变化，捕获并返回 False
            return False

    def select_time_and_wait(self, seat_num, start_time, end_time):
        """
        选好座位和时间，等待命令
        """
        logger.info("🔒 正在尝试锁定座位 %s (%s-%s)...", seat_num, start_time, end_time)
        try:
            # 1. 点击座位
            xpath = f'//div[contains(@class, "seat-name") and contains(text(), "{seat_num}")]'
            try:
                seat_elem = self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", seat_elem)
                seat_elem.click()
            except Exception:
                logger.warning("⚠️ 座位 %s 找不到或不可点击，跳过", seat_num)
                return False

            # 2. 等待弹窗出现
            try:
                # 显式等待预约框出现，时间可以长一点
                WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.CLASS_NAME, "reserve-box")))
            except TimeoutException:
                logger.warning("⚠️ 座位 %s 点击后未弹出预约框，跳过", seat_num)
                return False

            # 3. 选择开始时间 (Column 1)
            if not self.click_time_label(1, start_time):
                logger.warning("⚠️ 座位 %s 的开始时间 %s 不可选 (被占或未开放)", seat_num, start_time)
                self.close_popup()
                return False

            # 🔴 【核心修改】增加强制等待，确保右侧时间轴渲染出来
            time.sleep(0.5)

            # 4. 选择结束时间 (Column 2)
            # 增加 Timeout 到 3 秒，防止找不到元素
            if not self.click_time_label(2, end_time, timeout=3):
                logger.warning("⚠️ 座位 %s 的结束时间 %s 不可选，或元素未渲染", seat_num, end_time)
                self.close_popup()
                return False

            logger.info("✅ %s (%s-%s) 锁定成功！等待开火...", seat_num, start_time, end_time)
            return True

        except Exception as e:
            # 捕获所有选座异常
            logger.error("❌ 选座异常 %s: %s", seat_num, e)
            self.close_popup()
            return False

    def get_available_seats(self):
        """
        获取当前自习室页面上所有座位编号。
        返回座位编号字符串列表。
        """
        try:
            seat_elems = self.driver.find_elements(By.CSS_SELECTOR, "div.seat-name")
            seats = []
            for el in seat_elems:
                name = el.text.strip()
                if name:
                    seats.append(name)
            logger.info("🪑 当前页面共找到 %d 个座位", len(seats))
            return seats
        except Exception as e:
            logger.warning("⚠️ 获取座位列表失败: %s", e)
            return []

    def select_random_available(self, start_time, end_time, stop_event=None, exclude_seats=None):
        """
        从当前自习室随机选一个可用座位（排除已尝试失败的）。
        成功返回座位号，失败返回 None。
        """
        exclude = set(exclude_seats or [])
        all_seats = self.get_available_seats()
        candidates = [s for s in all_seats if s not in exclude]

        if not candidates:
            logger.info("💔 没有可尝试的候选座位了（全部已排除或无座位）")
            return None

        random.shuffle(candidates)
        logger.info("🎲 随机回退：将尝试 %d 个候选座位", len(candidates))

        for seat in candidates:
            if stop_event and stop_event.is_set():
                break
            if self.select_time_and_wait(seat, start_time, end_time):
                return seat

        return None

    def fire_submit(self):
        """
        开火！点击提交按钮
        """
        try:
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, ".el-button.submit-btn")
            submit_btn.click()
            return True
        except Exception as e:
            logger.error("❌ 提交失败: %s", e)
            return False

    def check_result(self):
        """检查结果"""
        try:
            # 等待所有可能的弹窗/提示文本
            res_element = self.wait.until(EC.any_of(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '预约成功')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '有效预约')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '已有预约')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '预约失败')]"))
            ))

            result_text = res_element.text
            logger.info("📝 结果反馈: %s", result_text)

            # 如果是成功提示，关闭弹窗
            if "预约成功" in result_text or "有效预约" in result_text:
                self.close_popup()
                return True
            # 如果是失败提示，也需要关闭弹窗并返回失败
            elif "已有预约" in result_text or "预约失败" in result_text:
                self._save_failure_screenshot("booking_failed")
                self.close_popup()
                return False  # 返回 False，触发重试/恢复逻辑

            self._save_failure_screenshot("unknown_result")
            return False  # 默认失败
        except Exception:
            self._save_failure_screenshot("check_timeout")
            return False

    def close_popup(self):
        """
        关闭座位预约弹窗（通用关闭逻辑）
        """
        logger.info("❌ 正在尝试关闭预约弹窗...")
        try:
            close_btn_xpath = '//div[contains(@class, "reserve-box")]//i[contains(@class, "el-icon-close")]'

            # 使用较短的等待时间，因为我们知道弹窗应该还在
            close_btn = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, close_btn_xpath))
            )
            close_btn.click()
            # 确保弹窗消失
            WebDriverWait(self.driver, 2).until(
                EC.invisibility_of_element_located((By.CLASS_NAME, "reserve-box"))
            )
            logger.info("✅ 预约弹窗已关闭。")
            return True
        except Exception:
            # 如果找不到关闭按钮或弹窗已消失，则忽略
            logger.warning("⚠️ 预约弹窗似乎已经关闭或找不到关闭按钮。")
            return False