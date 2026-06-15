from unittest import mock
import pytest

# Import the module under test
import core.driver as driver_mod
import config

def test_driverpath_priority(tmp_path, monkeypatch):
    # Create a fake driver executable
    fake = tmp_path / "fake_driver.exe"
    fake.write_text("")

    # Mock the config attributes directly
    monkeypatch.setattr(config, "DRIVER_PATH", str(fake))
    monkeypatch.setattr(config, "BROWSER", "edge")

    # reload module to pick up new config references
    import importlib
    importlib.reload(driver_mod)

    # Mock webdriver.Edge to avoid launching real browser
    class FakeWebDriver:
        def set_page_load_timeout(self, t):
            pass

    with mock.patch("selenium.webdriver.Edge", return_value=FakeWebDriver()) as mock_edge:
        d = driver_mod.get_driver()
        assert isinstance(d, FakeWebDriver)
        mock_edge.assert_called_once()


def test_webdriver_manager_download(monkeypatch, tmp_path):
    # Ensure DRIVER_PATH is empty
    monkeypatch.setattr(config, "DRIVER_PATH", "")
    monkeypatch.setattr(config, "BROWSER", "edge")

    # reload module
    import importlib
    importlib.reload(driver_mod)

    # Mock webdriver-manager install
    fake_path = str(tmp_path / "downloaded_msedgedriver.exe")
    open(fake_path, "w").close()

    class FakeManager:
        def install(self):
            return fake_path

    monkeypatch.setattr(driver_mod, "EdgeChromiumDriverManager", lambda **kw: FakeManager())

    class FakeWebDriver:
        def set_page_load_timeout(self, t):
            pass

    with mock.patch("selenium.webdriver.Edge", return_value=FakeWebDriver()) as mock_edge:
        d = driver_mod.get_driver()
        assert isinstance(d, FakeWebDriver)
        mock_edge.assert_called_once()


def test_all_fail_raises(monkeypatch):
    # Simulate no DRIVER_PATH, no webdriver-manager available, and webdriver.Edge raising
    monkeypatch.setattr(config, "DRIVER_PATH", "")
    monkeypatch.setattr(config, "BROWSER", "edge")

    # reload modules
    import importlib
    importlib.reload(driver_mod)

    # Ensure webdriver-manager unavailable
    monkeypatch.setattr(driver_mod, "_HAS_WM", False)

    def raise_on_edge(*args, **kwargs):
        raise RuntimeError("no driver")

    with mock.patch("selenium.webdriver.Edge", side_effect=raise_on_edge):
        with pytest.raises(RuntimeError):
            driver_mod.get_driver()
