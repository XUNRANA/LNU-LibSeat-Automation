from io import BytesIO

from PIL import Image

from core.captcha import ClickCaptchaSolver


def make_png_bytes(width=120, height=80, color=(255, 255, 255)):
    img = Image.new("RGB", (width, height), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_extract_target_chars_supports_1_to_4():
    solver = object.__new__(ClickCaptchaSolver)

    assert solver._extract_target_chars("机") == ["机"]
    assert solver._extract_target_chars("请依次点击农改车") == ["农", "改", "车"]
    assert solver._extract_target_chars("请按顺序点击春夏秋冬") == ["春", "夏", "秋", "冬"]
    assert solver._extract_target_chars("请按顺序点击天地玄黄宇") == ["地", "玄", "黄", "宇"]


def test_solve_matches_click_order_for_multi_chars(monkeypatch):
    solver = object.__new__(ClickCaptchaSolver)

    class FakeOCR:
        def classification(self, _):
            return "请依次点击农改车"

    class FakeDet:
        def detection(self, _):
            # center: (15,20), (40,20), (65,20)
            return [(5, 10, 25, 30), (30, 10, 50, 30), (55, 10, 75, 30)]

    solver.ocr = FakeOCR()
    solver.det = FakeDet()

    # 背景3个区域分别识别成：车、农、改
    candidates = iter([
        (["车"], ["车"]),
        (["农"], ["农"]),
        (["改"], ["改"]),
    ])
    monkeypatch.setattr(solver, "_extract_char_candidates", lambda _crop: next(candidates))

    click_points = solver.solve(target_bytes=b"unused", bg_bytes=make_png_bytes())

    # 必须按目标串“农改车”顺序返回坐标
    assert click_points == [(40, 20), (65, 20), (15, 20)]
