"""capture 纯函数测试：04 验收清单第 1 条——坐标对拍不靠肉眼。

map_rect 是整条截屏链路的地基（物理像素抓帧 vs 逻辑坐标框选，
本机 150% 缩放），这里钉死换算；比例错 → 裁出来的题图错位。
"""

import io
import sys

from PIL import Image

from spore_client.capture import (
    JPEG_LONG_EDGE,
    ML_TIMEOUT_MS,
    OcrLine,
    encode_jpeg,
    map_rect,
    suggest,
    too_small,
    unmap_rect,
)


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


# ---------- Suggestor（忠实移植 Mobile Suggestor.java，判据对拍 SuggestTest） ----------
# 坐标系 = 冻结帧像素；断言用不等式/精确 pad（阈值与 Java 逐字一致，勿「优化」）

FRAME_W, FRAME_H = 1080, 2400


def line(left: int, top: int, right: int, bottom: int, text: str) -> OcrLine:
    return OcrLine(left, top, right, bottom, text)


def test_suggest_merges_question_block_and_covers_it():
    # 三行题干+选项聚成一块，建议框覆盖整块（含外扩 pad）
    lines = [
        line(80, 300, 1000, 360, "1、下列哪个说法是正确的？"),
        line(80, 380, 600, 430, "A. 说法甲"),
        line(80, 450, 600, 500, "B. 说法乙"),
    ]
    box = suggest(lines, FRAME_W, FRAME_H)
    assert box is not None
    left, top, right, bottom = box
    assert left <= 80 and top <= 300 and right >= 1000 and bottom >= 500
    assert right - left < FRAME_W    # 真按块聚类，不是偷懒返回全屏


def test_suggest_prefers_question_over_title():
    # 标题（无问句信号）与题块分开时，选中题块而不是上方标题
    lines = [
        line(80, 100, 400, 150, "语文随堂练习"),
        line(80, 300, 1000, 360, "2、下列计算正确的是（  ）？"),
        line(80, 380, 600, 430, "A. 2+2=5"),
    ]
    box = suggest(lines, FRAME_W, FRAME_H)
    assert box is not None
    assert box[1] >= 250              # 题块在下，框顶应从题干附近开始


def test_suggest_empty_input_returns_none():
    # 空输入 / 空文本 / 非法帧尺寸 → None（调用方退手动拖框）
    assert suggest([], FRAME_W, FRAME_H) is None
    assert suggest(None, FRAME_W, FRAME_H) is None
    assert suggest([line(80, 300, 1000, 360, "   ")],
                   FRAME_W, FRAME_H) is None      # 全空白文本不算
    assert suggest([line(80, 300, 1000, 360, "1、下列对吗？")], 0, FRAME_H) is None


def test_suggest_tiny_block_rejected():
    # 太小的块没资格当建议框：宽 < 0.10×帧宽 一律不建议（哪怕带问号）
    assert suggest([line(500, 1000, 530, 1040, "1+1=?")],
                   FRAME_W, FRAME_H) is None
    # 对照：同文本放到帧宽 10% 以上就该出框（门槛是几何，不是内容）
    assert suggest([line(500, 1000, 700, 1040, "1+1=?")],
                   FRAME_W, FRAME_H) is not None


def test_suggest_columns_do_not_glue():
    # 两列同高文本不跨列粘连：问句块独立成块且胜出
    lines = [
        line(60, 2000, 400, 2050, "答案在最后"),
        line(520, 2000, 1020, 2050, "第 3 题，哪一项是正确的？"),
    ]
    box = suggest(lines, FRAME_W, FRAME_H)
    assert box is not None
    assert box[0] > 400               # 应选中右列问句块


def test_suggest_ties_pick_topmost():
    # 信号等价时取先（上方）出现的块——平手规则钉死，防实现漂移
    lines = [
        line(80, 400, 1000, 500, "第一问，哪个对？"),
        line(80, 900, 1000, 1000, "第二问，哪个对？"),
    ]
    box = suggest(lines, FRAME_W, FRAME_H)
    assert box is not None
    assert box[1] < 700               # 平手取上方块


def test_suggest_numbering_bonus_wins_tie():
    # 几何/文本量/问号全同 → 只有题号 +25 分出胜负（题号块在**下**方，
    # 排除「平手取上方」的干扰：赢只能靠加分）
    lines = [
        line(80, 400, 1000, 500, "甲乙丙丁戊己对。"),
        line(80, 900, 1000, 1000, "1、甲乙丙丁戊己"),
    ]
    box = suggest(lines, FRAME_W, FRAME_H)
    assert box is not None
    assert box[1] >= 700              # 选中下方题号块（+25）


def test_suggest_question_mark_bonus_wins_tie():
    # 全同只有问号差 → +40 的问句块胜（问句块在下方）
    lines = [
        line(80, 400, 1000, 500, "甲乙丙丁戊己对。"),
        line(80, 900, 1000, 1000, "甲乙丙丁戊己对？"),
    ]
    box = suggest(lines, FRAME_W, FRAME_H)
    assert box is not None
    assert box[1] >= 700              # 选中下方问句块（+40）


def test_suggest_cue_bonus_counts_once():
    # 下块命中 3 个 cue、上块只 1 个 → 仍平手（一票多词也只加一次）
    # → 按平手规则上方胜；若实现让 cue 叠加，下块会赢，此断言即红
    lines = [
        line(80, 400, 1000, 500, "下列甲乙丙丁戊己"),
        line(80, 900, 1000, 1000, "选择判断计算甲乙"),
    ]
    box = suggest(lines, FRAME_W, FRAME_H)
    assert box is not None
    assert box[1] < 700               # 平手 → 上方块（cue 不堆叠）


def test_suggest_padding_exact_and_clamped():
    # pad = int(max(8, min(24, 0.02×max(块宽,块高))))：800 宽块 → 精确 16
    box = suggest([line(200, 600, 1000, 700, "1、下列哪个说法是对的？")],
                  FRAME_W, FRAME_H)
    assert box == (184, 584, 1016, 716)
    # 下限 8（0.02×120 = 2.4 → 仍是 8）
    box = suggest([line(300, 600, 420, 700, "1、下列哪个说法是对的？")],
                  FRAME_W, FRAME_H)
    assert box == (292, 592, 428, 708)
    # 上限 24（0.02×1500 = 30 → 截到 24）
    box = suggest([line(100, 300, 1000, 1800, "1、下列哪个说法是对的？")],
                  FRAME_W, FRAME_H)
    assert box == (76, 276, 1024, 1824)
    # clamp 到帧内：贴左上角 → 0/0；贴右下角 → 帧宽/帧高
    box = suggest([line(0, 0, 500, 120, "1、下列哪个说法是对的？")],
                  FRAME_W, FRAME_H)
    assert box[0] == 0 and box[1] == 0
    box = suggest([line(580, 2300, 1080, 2390, "1、下列哪个说法是对的？")],
                  FRAME_W, FRAME_H)
    assert box[2] == FRAME_W and box[3] == FRAME_H


def test_unmap_rect_roundtrips_with_map_rect():
    # 像素建议框 → 逻辑选区（map_rect 的逆向，覆盖层预填用）
    logical, pixel = (1493, 933), (2239, 1399)
    px = (150, 149, 301, 226)
    x, y, w, h = unmap_rect(px, logical, pixel)
    back = map_rect((x, y, w, h), logical, pixel)
    assert all(abs(a - b) <= 1 for a, b in zip(back, px, strict=False))


def test_ml_timeout_matches_mobile():
    # 契约：超时与 Mobile ML_TIMEOUT_MS 同值
    assert ML_TIMEOUT_MS == 8000


def test_rapidocr_lazy_not_imported_by_default():
    # 关着开关 = 零 OCR：模块导入路径不许拉起 rapidocr（懒加载纪律）
    import spore_client.capture as cap
    assert "rapidocr" not in sys.modules
    assert cap._ocr_engine is None
