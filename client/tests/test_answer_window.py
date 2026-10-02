"""place_near 纯函数：04 §四「浮窗出现在选区附近，越界钳回屏内」。

浮窗定位错 → 用户找不到回答面板；这里钉死贴选区与两条钳位规则。
"""

from spore_client.answer_window import place_near

PANEL = (460, 560)        # AnswerWindow 默认尺寸
SCREEN = (1493, 933)      # 本机逻辑分辨率（150% 缩放）
MARGIN = 12


def test_places_right_of_selection_when_room():
    x, y = place_near((100, 100, 300, 200), *PANEL, *SCREEN)
    assert x == 100 + 300 + MARGIN          # 选区右缘外 12
    assert x + PANEL[0] <= SCREEN[0]        # 不越出屏幕右缘


def test_falls_back_left_when_right_side_full():
    # 选区贴屏幕右缘 → 右侧放不下，翻到左侧
    x, y = place_near((1100, 100, 380, 200), *PANEL, *SCREEN)
    assert x + PANEL[0] == 1100 - MARGIN    # 紧贴选区左缘外 12
    assert x >= MARGIN


def test_clamps_left_when_selection_spans_screen():
    # 选区横贯全屏：左右都放不下 → 钳回屏幕左缘（不许负坐标）
    x, y = place_near((100, 100, 1200, 200), *PANEL, *SCREEN)
    assert x == MARGIN


def test_vertical_center_clamped_to_top():
    # 选区贴屏幕上缘 → 居中算出负 y，钳回上缘
    x, y = place_near((100, 100, 300, 200), *PANEL, *SCREEN)
    assert y == MARGIN


def test_vertical_center_clamped_to_bottom():
    # 选区贴屏幕下缘 → 居中算出超界 y，钳回下缘
    x, y = place_near((100, 800, 300, 100), *PANEL, *SCREEN)
    assert y == SCREEN[1] - PANEL[1] - MARGIN


def test_panel_sits_fully_on_screen():
    for sel in [(0, 0, 60, 40), (1433, 893, 60, 40), (700, 450, 400, 300)]:
        x, y = place_near(sel, *PANEL, *SCREEN)
        assert 0 <= x <= SCREEN[0] - PANEL[0]
        assert 0 <= y <= SCREEN[1] - PANEL[1]
