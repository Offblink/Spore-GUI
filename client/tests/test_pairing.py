"""扫码配对纯逻辑（2026-10-03 自设置页迁到主窗左下角头像）。"""

import json

from spore_client.pairing import (
    _is_lan_ipv4,
    api_base_for_phone,
    build_payload,
    initial_of,
    lan_ipv4,
    rewrite_loopback,
)


def test_initial_of_takes_first_nonblank_char_upper():
    assert initial_of("周予") == "周"        # 中文昵称 → 首字
    assert initial_of("", "alice") == "A"    # 昵称空 → 用户名
    assert initial_of(None, "  bob ") == "B"
    assert initial_of() == "?"               # 都没有 → 占位


def test_payload_shape_unchanged_from_settings_qr():
    # 载荷形状是手机端契约（02 认证节拍板）：迁移只挪 UI 不改字节
    p = json.loads(build_payload("http://127.0.0.1:8080/api", "tk-1"))
    assert p == {"v": 1, "api": "http://127.0.0.1:8080/api", "token": "tk-1"}


def test_rewrite_loopback_swaps_host_keeps_port_and_path():
    assert (rewrite_loopback("http://127.0.0.1:8080/api", "192.168.1.5")
            == "http://192.168.1.5:8080/api")
    assert (rewrite_loopback("http://localhost:8080/api", "10.0.0.2")
            == "http://10.0.0.2:8080/api")
    # 无端口也行
    assert (rewrite_loopback("http://127.0.0.1/api", "172.16.0.9")
            == "http://172.16.0.9/api")


def test_rewrite_loopback_keeps_non_loopback_and_bad_ip():
    # 用户已手填局域网地址：别动
    assert (rewrite_loopback("http://192.168.1.9:9000/api", "192.168.1.5")
            == "http://192.168.1.9:9000/api")
    # ip 不是局域网（空/回环/TUN 探测段/APIPA/公网/垃圾）：保持回环原样，
    # 手机确认框侧仍可手改——换了假地址才是真坑
    for bad in ("", "127.0.0.1", "198.18.0.1", "169.254.4.4", "8.8.8.8",
                "1.2.3.256", "nonsense"):
        assert (rewrite_loopback("http://127.0.0.1:8080/api", bad)
                == "http://127.0.0.1:8080/api")


def test_is_lan_ipv4_is_rfc1918_only():
    assert _is_lan_ipv4("10.1.2.3")
    assert _is_lan_ipv4("172.16.0.1")
    assert _is_lan_ipv4("172.31.255.254")
    assert _is_lan_ipv4("192.168.0.1")
    for bad in ("172.15.0.1", "172.32.0.1", "192.169.0.1", "127.0.0.1",
                "198.18.0.1", "169.254.1.1", "1.2.3.4", "1.2.3", "1.2.3.256",
                "a.b.c.d", "", "0.0.0.0"):
        assert not _is_lan_ipv4(bad), bad


def test_lan_ipv4_is_empty_or_private():
    # 环境相关（有无网卡/路由），只钉形状：要么空串要么 RFC1918
    ip = lan_ipv4()
    assert ip == "" or _is_lan_ipv4(ip)


def test_api_base_for_phone_never_silently_returns_loopback_when_lan_exists():
    base = "http://127.0.0.1:8080/api"
    out = api_base_for_phone(base)
    assert out == base or ("127.0.0.1" not in out and out.startswith("http://"))
