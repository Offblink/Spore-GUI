"""place_near 纯函数 + 追问小节标位置（04 §四 与 2026-10-03 反馈）。

浮窗定位错 → 用户找不到回答面板（钉死贴选区与两条钳位规则）；
chat-start 的「追问」灰字必须画在用户追问气泡**上方**（用户点名的顺序，
旧实现是先检索小票才见「追问」）。
"""

from PySide6.QtWidgets import QLabel

from spore_client.answer.settings import LlmSettings
from spore_client.answer_window import AnswerWindow, place_near

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
    # 选区贴屏幕上缘 → 纵向算出负 y → 钳回上缘
    x, y = place_near((100, 100, 300, 200), *PANEL, *SCREEN)
    assert y == MARGIN


def test_vertical_center_clamped_to_bottom():
    # 选区贴屏幕下缘 → 纵向超界 → 钳回下缘
    x, y = place_near((100, 800, 300, 200), *PANEL, *SCREEN)
    assert y == SCREEN[1] - PANEL[1] - MARGIN


def test_panel_sits_fully_on_screen():
    for sel in [(0, 0, 60, 40), (1433, 893, 60, 40), (700, 450, 400, 300)]:
        x, y = place_near(sel, *PANEL, *SCREEN)
        assert 0 <= x <= SCREEN[0] - PANEL[0]
        assert 0 <= y <= SCREEN[1] - PANEL[1]


# ---------- 追问小节标位置（2026-10-03 反馈） ----------

def test_chat_start_puts_followup_label_above_user_bubble(qapp):
    from PySide6.QtWidgets import QFrame

    win = AnswerWindow(LlmSettings(api_key="sk-test"))
    win.on_event({"type": "chat-start", "idx": 1, "text": "在吗"})
    items = [win._blocks_box.itemAt(i).widget()
             for i in range(win._blocks_box.count())]
    sec_idx = next(i for i, w in enumerate(items)
                   if isinstance(w, QLabel) and w.text() == "追问")
    bubble_idx = next(i for i, w in enumerate(items)
                      if isinstance(w, QFrame)
                      and w.objectName() == "userBubble")
    assert sec_idx < bubble_idx            # 灰字小节标在用户追问气泡上方
    user_texts = [b["user_lbl"].text() for b in win._blocks
                  if b["kind"] == "user" and b["user_lbl"] is not None]
    assert "在吗" in user_texts
