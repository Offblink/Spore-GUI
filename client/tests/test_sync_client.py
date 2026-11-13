"""同步客户端：地址归一、R 包装解包、错误分类、附件原始字节。"""

import json

import httpx
import pytest

from spore_client.sync_client import (
    NetworkError,
    SyncClient,
    SyncError,
    normalize_api,
)


@pytest.mark.parametrize("raw, want", [
    ("192.168.1.5:19080", "http://192.168.1.5:19080/api"),
    ("http://192.168.1.5:19080", "http://192.168.1.5:19080/api"),
    ("http://host:19080/", "http://host:19080/api"),
    ("http://host:19080/api", "http://host:19080/api"),
    ("http://host:19080/api/", "http://host:19080/api"),
    ("https://spore.example.com", "https://spore.example.com/api"),
    ("", ""),
])
def test_normalize_api(raw, want):
    assert normalize_api(raw) == want


def client_with(handler, token=""):
    return SyncClient("h:19080", token, transport=httpx.MockTransport(handler))


def test_login_unpacks_r_wrapper_and_sets_token():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("Authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={
            "code": 0, "message": "ok",
            "data": {"token": "jwt-1", "userId": 7, "nickname": "演示"}})

    c = client_with(handler)
    data = c.login("demo", "pw123456")
    assert data["token"] == "jwt-1"
    assert c.token == "jwt-1"
    assert seen["url"].endswith(":19080/api/auth/login")
    assert seen["auth"] is None                     # 登录是公开接口
    assert seen["body"] == {"username": "demo", "password": "pw123456"}


def test_business_error_carries_server_message():
    def handler(req):
        return httpx.Response(200, json={
            "code": 40103, "message": "口令不正确", "data": None})

    with pytest.raises(SyncError) as ei:
        client_with(handler).me()
    assert ei.value.code == 40103
    assert "口令不正确" in str(ei.value)


def test_non_json_body_is_business_error_not_crash():
    def handler(req):
        return httpx.Response(502, text="<html>bad gateway</html>")

    with pytest.raises(SyncError) as ei:
        client_with(handler).pull(0)
    assert "502" in str(ei.value)


def test_connect_failure_is_network_error():
    def handler(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(NetworkError):
        client_with(handler).pull(0)


def test_pull_sends_cursor_and_limit():
    seen = {}

    def handler(req):
        seen["params"] = dict(req.url.params)
        seen["auth"] = req.headers.get("Authorization")
        return httpx.Response(200, json={
            "code": 0, "data": {"categories": [], "articles": [],
                                "nextCursor": 0}})

    client_with(handler, token="t1").pull(1234, 200)
    assert seen["params"] == {"cursor": "1234", "limit": "200"}
    assert seen["auth"] == "Bearer t1"


def test_push_body_shape():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={
            "code": 0, "data": {"results": [{"id": "a1", "accepted": True}]}})

    res = client_with(handler, token="t").push(
        [{"id": "c1"}], [{"id": "a1"}])
    assert seen["body"] == {"categories": [{"id": "c1"}],
                            "articles": [{"id": "a1"}]}
    assert res == [{"id": "a1", "accepted": True}]


def test_pull_attachment_404_is_empty_not_error():
    def handler(req):
        assert req.url.params["path"] == "2026/a1.jpg"
        return httpx.Response(404)

    assert client_with(handler, token="t").pull_attachment("2026/a1.jpg") is None


def test_pull_attachment_returns_raw_bytes():
    def handler(req):
        return httpx.Response(200, content=b"\xff\xd8jpeg")

    blob = client_with(handler, token="t").pull_attachment("a1.jpg")
    assert blob == b"\xff\xd8jpeg"


def test_push_attachment_is_multipart_with_article_id(tmp_path):
    seen = {}
    img = tmp_path / "shot.jpg"
    img.write_bytes(b"jpgbytes")

    def handler(req):
        seen["params"] = dict(req.url.params)
        seen["ctype"] = req.headers.get("Content-Type", "")
        seen["body"] = req.content
        return httpx.Response(200, json={"code": 0, "data": "2026/a1.jpg"})

    rel = client_with(handler, token="t").push_attachment("a1", img)
    assert rel == "2026/a1.jpg"
    assert seen["params"] == {"articleId": "a1"}
    assert seen["ctype"].startswith("multipart/form-data")
    assert b"jpgbytes" in seen["body"]
