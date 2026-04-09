import os
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.chrome.service import Service as ChromeService
from core.logger import get_logger

def _cfg(attr, default=""):
    import config
    return getattr(config, attr, default)

logger = get_logger(__name__)

# Import webdriver-manager lazily to avoid hard dependency during import-time in tests
try:
    from webdriver_manager.microsoft import EdgeChromiumDriverManager
    from webdriver_manager.chrome import ChromeDriverManager
    _HAS_WM = True
except Exception:
    EdgeChromiumDriverManager = None
    ChromeDriverManager = None
    _HAS_WM = False


def _build_options(browser: str):
    """Return (options, service_class) appropriate for the requested browser."""
    if browser == 'chrome':
        opts = ChromeOptions()
    else:
        opts = EdgeOptions()

    # common options
    opts.page_load_strategy = 'eager'
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_argument("--lang=zh-CN")
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    
    # 修改 User-Agent，去掉可能的 Edge/WebDriver 泄露特征
    opts.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0')

    # suppress some verbose logging from Chromium and hide automation info
    try:
        opts.add_experimental_option('excludeSwitches', ['enable-logging', 'enable-automation', 'ignore-certificate-errors'])
        opts.add_experimental_option('useAutomationExtension', False)
    except Exception:
        # older selenium/option implementations may not support experimental options
        pass

    if _cfg('HEADLESS', True):
        # selenium 4 new headless flag for Chromium-based browsers
        opts.add_argument('--headless=new')

    return opts


def _download_driver_with_manager(browser: str):
    """Attempt to download driver using webdriver-manager. Return path or None."""
    if not _HAS_WM:
        logger.debug("webdriver-manager not available; skipping download attempt.")
        return None

    try:
        # If user requested a custom cache directory, set the env var webdriver-manager reads.
        if _cfg('WEBDRIVER_CACHE'):
            os.environ['WDM_LOCAL'] = _cfg('WEBDRIVER_CACHE')

        if browser == 'chrome':
            mgr = ChromeDriverManager()
        else:
            mgr = EdgeChromiumDriverManager()

        path = mgr.install()
        logger.info("webdriver-manager installed driver: %s", path)
        return path
    except TypeError as e:
        # Some webdriver-manager versions may reject unexpected kwargs; fallback gracefully
        logger.warning("webdriver-manager init failed (TypeError): %s", e)
        try:
            if browser == 'chrome':
                mgr = ChromeDriverManager()
            else:
                mgr = EdgeChromiumDriverManager()
            path = mgr.install()
            logger.info("webdriver-manager installed driver on retry: %s", path)
            return path
        except Exception as e2:
            logger.warning("webdriver-manager failed to download driver on retry: %s", e2)
            return None
    except Exception as e:
        logger.warning("webdriver-manager failed to download driver: %s", e)
        return None


def _apply_stealth(driver):
    """
    Remove all CDP JS injections. 
    Modern WAFs can detect Object.defineProperty on native navigator objects.
    We rely entirely on --disable-blink-features=AutomationControlled which 
    removes the webdriver flag at the C++ browser engine level without JS traces.
    """
    try:
        # Just logging, no JS manipulation
        logger.debug("Relying wholly on C++ blink flags for stealth.")
    except Exception as e:
        pass


def _clear_stale_driver_cache(browser: str):
    """Remove stale driver binaries from the Selenium cache so SeleniumManager re-downloads."""
    import shutil
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "selenium")
    driver_name = "msedgedriver" if browser != "chrome" else "chromedriver"
    target = os.path.join(cache_dir, driver_name)
    if os.path.isdir(target):
        try:
            shutil.rmtree(target)
            logger.info("Cleared stale driver cache: %s", target)
        except Exception as exc:
            logger.warning("Failed to clear cache %s: %s", target, exc)


def _validate_executable(path: str) -> bool:
    if not path:
        return False
    # On Windows the execute bit isn't always set; check file existence
    return os.path.exists(path)


def get_driver(user_data_dir: str = None):
    """Create a configured webdriver instance for the configured browser.

    Resolution order for driver executable:
    1. Explicit DRIVER_PATH env var (full path)
    2. webdriver-manager downloaded driver
    3. Fall back to system PATH (webdriver.Edge()/webdriver.Chrome() rely on PATH)

    Raises a RuntimeError with actionable guidance if no driver is available.
    """
    browser = (_cfg('BROWSER', 'edge') or 'edge').lower()

    opts = _build_options(browser)

    if user_data_dir:
        opts.add_argument(f'--user-data-dir={user_data_dir}')

    # 1) Try explicit DRIVER_PATH
    DRIVER_PATH = _cfg('DRIVER_PATH')
    if DRIVER_PATH:
        if _validate_executable(DRIVER_PATH):
            logger.info("Using driver from DRIVER_PATH: %s", DRIVER_PATH)
            # silence service logs
            service = EdgeService(executable_path=DRIVER_PATH, log_path=os.devnull) if browser != 'chrome' else ChromeService(executable_path=DRIVER_PATH, log_path=os.devnull)
            drv = webdriver.Edge(service=service, options=opts) if browser != 'chrome' else webdriver.Chrome(service=service, options=opts)
            drv.set_page_load_timeout(30)
            _apply_stealth(drv)
            return drv
        else:
            logger.warning("DRIVER_PATH is set but executable not found: %s", DRIVER_PATH)

    # 2) Try webdriver-manager
    downloaded = _download_driver_with_manager(browser)
    if downloaded and _validate_executable(downloaded):
        logger.info("Using webdriver-manager downloaded driver: %s", downloaded)
        # silence service logs
        service = EdgeService(executable_path=downloaded, log_path=os.devnull) if browser != 'chrome' else ChromeService(executable_path=downloaded, log_path=os.devnull)
        try:
            drv = webdriver.Edge(service=service, options=opts) if browser != 'chrome' else webdriver.Chrome(service=service, options=opts)
            drv.set_page_load_timeout(30)
            _apply_stealth(drv)
            return drv
        except Exception as e:
            logger.warning("webdriver-manager driver failed (version mismatch?): %s", e)
            logger.info("Clearing stale driver caches before Selenium auto-download...")
            _clear_stale_driver_cache(browser)

    # 3) Finally, let Selenium 4 built-in SeleniumManager auto-resolve the correct driver
    try:
        logger.info("Attempting to start browser using Selenium built-in SeleniumManager...")
        if browser != 'chrome':
            service = EdgeService(log_path=os.devnull)
            drv = webdriver.Edge(service=service, options=opts)
        else:
            service = ChromeService(log_path=os.devnull)
            drv = webdriver.Chrome(service=service, options=opts)
        drv.set_page_load_timeout(30)
        _apply_stealth(drv)
        return drv
    except Exception as e:
        msg = (
            "Cannot start browser driver.\n"
            "Tried DRIVER_PATH, webdriver-manager download, and Selenium SeleniumManager.\n"
            "Suggested actions:\n"
            "  1) Ensure network access so SeleniumManager can download the matching driver.\n"
            "  2) Or manually download the matching driver and set DRIVER_PATH env var.\n"
            "  3) Place driver executable in your PATH.\n"
        )
        logger.exception(msg)
        raise RuntimeError(msg) from e

