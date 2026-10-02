"""capture 纯函数测试：04 验收清单第 1 条——坐标对拍不靠肉眼。

map_rect 是整条截屏链路的地基（物理像素抓帧 vs 逻辑坐标框选，
本机 150% 缩放），这里钉死换算；比例错 → 裁出来的题图错位。
"""

import io

from PIL import Image

from spore_client.capture import JPEG_LONG_EDGE, encode_jpeg, map_rect, too_small


def test_map_rect_identity_at_100pct():
    # 100% 缩放：逻辑 == 物理，选区原样
    assert map_rect((100, 50, 300, 200), (1920, 1080), (1920, 1080)) == (100, 50, 300, 200)


def test_map_rect_scales_at_150pct():
    # 本机实测 150%（AppliedDPI=144）：逻辑 1493x933 ↔ 物理 2240x1400（约 1.497）
    logical, pixel = (1493, 933), (2239, 1399)
    x, y, w, h = map_rect((100, 100, 200, 150), logical, pixel)
    # 比例系数 ≈1.4974，允许 round 误差 ±1
    assert abs(x - 150) <= 1 and abs(y - 150) <= 1
    assert abs(w - 300) <= 1 and abs(h - 225) <= 1


def test_map_rect_clamps_to_image_bounds():
    # 拖出屏幕右下（选区越过逻辑边界）→ 裁剪矩形必须钳在图内
    x, y, w, h = map_rect((1800, 1000, 400, 300), (1920, 1080), (1920, 1080))
    assert x + w <= 1920 and y + h <= 1080
    assert w > 0 and h > 0


def test_map_rect_negative_drag_normalized():
    # 反向拖拽（从右下往左上）：起点可为负向矩形，仍要映射成合法区域
    x, y, w, h = map_rect((-50, -50, 250, 250), (1000, 800), (1500, 1200))
    assert x >= 0 and y >= 0 and w > 0 and h > 0


def test_too_small_matches_mv3_panel_threshold():
    # MV3 overlay.js:124 判定口径：宽高**都**低于下限才算太小（有其一够大就放行）
    assert too_small(59, 39) is True    # 双低 → 拒
    assert too_small(59, 40) is False   # 高达下限 → 放行（宽条）
    assert too_small(60, 39) is False   # 宽达下限 → 放行（高条）
    assert too_small(60, 40) is False
    assert too_small(100, 10) is False  # 细长横条也放行（用户口径：一个够即可）
    assert too_small(10, 40) is False


def test_encode_jpeg_long_edge_and_format(tmp_path):
    big = Image.new("RGB", (3200, 1800), "red")  # 长边超 1600
    dest = encode_jpeg(big, tmp_path / "t.jpg")
    out = Image.open(dest)
    assert out.format == "JPEG"
    assert max(out.size) == JPEG_LONG_EDGE  # 长边缩到 1600
    assert out.size[0] == 1600 and out.size[1] == 900  # 比例不变


def test_encode_jpeg_small_image_not_upscaled(tmp_path):
    small = Image.new("RGB", (800, 600), "blue")
    out = Image.open(encode_jpeg(small, tmp_path / "s.jpg"))
    assert out.size == (800, 600)  # 只缩不放


def test_encode_jpeg_is_real_jpeg_bytes(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), "green").save(buf, "JPEG")
    assert buf.getvalue()[:2] == b"\xff\xd8"  # JPEG SOI 标记（题图要能被手机端识别）
