import os
import pytest
import time

from core.driver import get_driver


@pytest.mark.smoke
def test_smoke_launch_and_get_title():
    """Smoke test: actually start a browser, navigate to example.com and assert the title.

    This test should be run manually on a machine with a browser installed, or in CI on a runner
    that has a browser available. It is marked with `smoke` so it is excluded by default.
    To skip on environments that cannot run browsers, set SKIP_DRIVER_SMOKE=1 in env.
    """
    if os.getenv("SKIP_DRIVER_SMOKE", "0") == "1":
        pytest.skip("Skipping smoke tests (SKIP_DRIVER_SMOKE=1)")

    d = None
    try:
        d = get_driver()
        # give page a moment to load when running in CI/headless
        d.get("https://example.com")
        time.sleep(1)
        assert "Example Domain" in d.title
    finally:
        if d:
            try:
                d.quit()
            except Exception:
                pass

