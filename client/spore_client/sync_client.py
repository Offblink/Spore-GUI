"""Spore-Cloud REST 客户端（协议与 Spore-Mobile SyncClient / 旧 GUI api.py 一致）。

- 统一 R 包装 ``{code, message, data}``：``code != 0`` 抛 :class:`SyncError`，
  服务端原话直接给界面显示；
- 鉴权 ``Authorization: Bearer <token>``（网关唯一闸门；``/auth/login`` 是公开的）;
- ``pull/push`` 用游标增量 + LWW + 墓碑，见 Spore-Cloud ``SyncService``；
- 题图 ``push-attachment``（multipart 字段 ``file``）/ ``pull-attachment``（原始字节）。

地址归一与手机端 ``ServerConnector.normalizeApi`` 同款：裸 ``host:port``、
带不带 ``http://``、末尾带不带 ``/api`` 都认。不设代理（``trust_env=False``）——
目标通常是局域网/本机，Windows 上残留的 ``HTTP_PROXY`` 会把 127.0.0.1 也送进代理。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

import httpx

TIMEOUT = httpx.Timeout(10.0, read=60.0)


class SyncError(Exception):
    """服务端业务错误（含 401）：``code`` 是 R 包装里的业务码。"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = int(code)


class NetworkError(Exception):
    """连不上服务器（未启动 / 防火墙 / 端口写错）——与业务错误分开提示。"""


def normalize_api(raw: str) -> str:
    """``192.168.1.5:19080`` / ``http://h:19080`` / ``http://h:19080/api/`` → 带 /api 的基址。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    if not s.startswith(("http://", "https://")):
        s = "http://" + s
    s = s.rstrip("/")
    if not s.endswith("/api"):
        s += "/api"
    return s


class SyncClient:
    def __init__(self, api: str, token: str = "", transport=None):
        self.api = normalize_api(api)
        self.token = token or ""
        self._http = httpx.Client(timeout=TIMEOUT, follow_redirects=True,
                                  trust_env=False, transport=transport)

    def close(self) -> None:
        self._http.close()

    # ---------------------------------------------------------------- 认证
    def login(self, username: str, password: str) -> dict:
        """``POST /auth/login`` → ``{token,userId,username,nickname,roleCode}``。"""
        data = self._call("POST", "/auth/login",
                          json_body={"username": username, "password": password})
        token = str((data or {}).get("token") or "")
        if not token:
            raise SyncError(40101, "登录响应里没有 token")
        self.token = token
        return data

    def me(self) -> dict:
        return self._call("GET", "/users/me") or {}

    # ---------------------------------------------------------------- 同步
    def pull(self, cursor: int, limit: int = 200) -> dict:
        """``GET /sync/pull`` → ``{categories, articles, nextCursor}``。"""
        return self._call("GET", "/sync/pull",
                          params={"cursor": int(cursor), "limit": int(limit)}) or {}

    def push(self, categories: list[dict], articles: list[dict]) -> list[dict]:
        """``POST /sync/push`` → ``[{id, accepted}]``（accepted 只作参考）。"""
        data = self._call("POST", "/sync/push",
                          json_body={"categories": categories,
                                     "articles": articles}) or {}
        return data.get("results") or []

    def push_attachment(self, article_id: str, path: str | Path) -> str:
        """题图上推 → 服务端相对题库目录的路径（写回 ``article.attachment_path``）。"""
        p = Path(path)
        data = p.read_bytes()
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        rel = self._call("POST", "/sync/push-attachment",
                         params={"articleId": article_id},
                         files={"file": (p.name, data, mime)})
        return str(rel or "")

    def pull_attachment(self, rel_path: str) -> bytes | None:
        """题图下推；404 → ``None``（没图不是错误）。"""
        return self._call("GET", "/sync/pull-attachment",
                          params={"path": rel_path}, raw=True)

    # ---------------------------------------------------------------- 内部
    def _call(self, method: str, path: str, *, json_body=None, params=None,
              files=None, raw: bool = False):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            resp = self._http.request(method, self.api + path, headers=headers,
                                      json=json_body, params=params, files=files)
        except httpx.HTTPError as e:
            raise NetworkError(
                f"连不上 {self.api}（{e.__class__.__name__}）") from None

        if raw:
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                raise SyncError(resp.status_code, _snippet(resp))
            return resp.content

        try:
            body = resp.json()
        except ValueError:
            raise SyncError(resp.status_code,
                            f"服务端返回非 JSON（HTTP {resp.status_code}）") from None
        if not isinstance(body, dict):
            raise SyncError(resp.status_code, "服务端返回格式异常")
        code = body.get("code")
        if int(code or 0) != 0:
            raise SyncError(int(code or resp.status_code),
                            str(body.get("message") or "同步失败"))
        return body.get("data")


def _snippet(resp: httpx.Response) -> str:
    try:
        text = resp.text.strip().replace("\n", " ")
    except Exception:
        return f"HTTP {resp.status_code}"
    return f"HTTP {resp.status_code}: {text[:120]}"
