"""ApiClient 契约测试：对着本地 stub 后端跑真 HTTP，不 mock 自己的代码。

钉住的都是真踩过的坑：
- token 在 R 包装的 data 层（JavaFX 版曾在顶层找，JSONObject[\"token\"] not found）
- GET 不许带 body / POST 必须有 body（OkHttp 的 method GET must not have a request body）
- 业务错误码与中文 message 原样上抛
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from spore_client.api import ApiClient, ApiError, NetworkError


@pytest.fixture()
def backend():
    state = {}  # 原地 clear/update 保引用——测试持的是同一个 dict

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # 静默访问日志，别污染 pytest 输出
            pass

        def _record(self):
            n = int(self.headers.get("Content-Length") or 0)
            state.clear()
            state.update(
                method=self.command,
                path=self.path,
                headers=dict(self.headers),
                body=self.rfile.read(n) if n else b"",
            )

        def _reply(self, status, payload):
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self._record()
            self._reply(200, {"code": 0, "message": "ok", "data": {"username": "tester"}})

        def do_POST(self):
            self._record()
            body = json.loads(state.get("body") or b"{}")
            if self.path.endswith("/auth/login"):
                if body.get("password") == "wrong":
                    self._reply(401, {"code": 40101, "message": "用户名或密码错误",
                                      "data": None})
                else:
                    self._reply(200, {"code": 0, "message": "ok",
                                      "data": {"token": "tk-1", "userId": 1}})
            else:
                self._reply(200, {"code": 0, "message": "ok", "data": "dt-1"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    yield SimpleNamespace(client=ApiClient(f"http://127.0.0.1:{port}/api"), last=state)
    server.shutdown()


def test_login_pulls_token_out_of_data(backend):
    vo = backend.client.login("tester", "ok-pw")
    assert vo["token"] == "tk-1"
    assert backend.client.token == "tk-1"  # 登录成功后 token 已挂上


def test_business_error_raises_code_and_message(backend):
    with pytest.raises(ApiError) as ei:
        backend.client.login("tester", "wrong")
    assert ei.value.code == 40101
    assert str(ei.value) == "用户名或密码错误"  # 401 响应体也要解出来，不吞成网络错


def test_get_carries_bearer_but_no_body(backend):
    backend.client.token = "tk-1"
    backend.client.me()
    h = backend.last["headers"]
    assert h.get("Authorization") == "Bearer tk-1"
    assert h.get("Content-Length") is None  # GET 不许带 body（OkHttp 同款红线）
    assert backend.last["body"] == b""


def test_logout_posts_empty_body(backend):
    backend.client.token = "tk-1"
    backend.client.logout()
    assert backend.last["method"] == "POST"
    assert backend.last["headers"].get("Content-Length") == "0"  # POST 必须有 body
    assert backend.client.token is None  # 本地清 token 不受服务端响应影响


def test_unreachable_backend_raises_network_error():
    with pytest.raises(NetworkError):
        ApiClient("http://127.0.0.1:1/api").me()  # 端口 1 必然拒绝，秒失败不等 15s
