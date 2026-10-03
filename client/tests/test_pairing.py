"""扫码配对纯逻辑（2026-10-03 自设置页迁到主窗左下角头像）。"""

import json

from spore_client.pairing import build_payload, initial_of


def test_initial_of_takes_first_nonblank_char_upper():
    assert initial_of("周予") == "周"        # 中文昵称 → 首字
    assert initial_of("", "alice") == "A"    # 昵称空 → 用户名
    assert initial_of(None, "  bob ") == "B"
    assert initial_of() == "?"               # 都没有 → 占位


def test_payload_shape_unchanged_from_settings_qr():
    # 载荷形状是手机端契约（02 认证节拍板）：迁移只挪 UI 不改字节
    p = json.loads(build_payload("http://127.0.0.1:8080/api", "tk-1"))
    assert p == {"v": 1, "api": "http://127.0.0.1:8080/api", "token": "tk-1"}
