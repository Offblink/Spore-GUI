"""place_near 纯函数 + 历史会话转 Session + 外部代发追问。

浮窗定位错 → 用户找不到回答面板（钉死贴选区与两条钳位规则）；
历史会话转 Session 丢 backend_id/消息 → 追问开新会话、落库走错接口（§8-2）；
记录页「接着问」走 panel.send_text 进同一条发送链（2026-10-03 反馈）。
"""

from spore_client.answer.settings import LlmSettings
from spore_client.answer_window import (
    AnswerWindow,
    _msgs_of,
    _session_from_article,
    place_near,
)

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


# ---------- 历史会话 → 可接续 Session（2026-10-03 §8-2） ----------

def test_session_from_article_carries_backend_id_and_msgs():
    art = {"id": "20261002-abc", "title": "SQA 范围", "fav": 1,
           "status": "done",
           "messages": [{"role": "user", "kind": "chat", "text": "在吗",
                         "ts": 5},
                        {"role": "assistant", "kind": "answer", "ans": "A（对）",
                         "tools": ["检索 SQA 定义"]},
                        "畸形行"]}
    sess = _session_from_article(art, _msgs_of(art))
    assert sess.backend_id == "20261002-abc"   # turn-end 据此走 PUT 而非 POST
    assert sess.title == "SQA 范围" and sess.fav is True
    assert [m.role for m in sess.messages] == ["user", "assistant"]
    assert sess.messages[0].ts == 5            # ts 是排序依据，别丢
    assert sess.messages[1].tools == ["检索 SQA 定义"]


# ---------- 记录页代发追问（2026-10-03 反馈） ----------

def test_send_text_emits_followup_like_input_box(qapp):
    win = AnswerWindow(LlmSettings(api_key="sk-test"))
    got: list = []
    win.followupRequested.connect(got.append)
    assert win.send_text("  在吗 ") is True
    assert got == ["在吗"]                 # 与输入框 _send 同一条信号链
    assert win.send_text("   ") is False   # 空文本不发
