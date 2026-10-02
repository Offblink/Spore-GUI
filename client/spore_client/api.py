"""REST 客户端：与 Java ApiClient 同一套契约。

统一 R 包装 {code, message, data}：code!=0 抛 ApiError(code, message)。
base 默认 127.0.0.1:8080；手机/局域网场景由调用方 set_base()。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:8080/api"


class ApiError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class NetworkError(Exception):
    """连不上后端（未启动/防火墙）——与业务错误分开，UI 要给不同提示。"""


class ApiClient:
    def __init__(self, base: str = DEFAULT_BASE):
        self.base = base.rstrip("/")
        self.token: str | None = None

    # ---------- 认证 ----------
    def login(self, username: str, password: str) -> dict:
        data = self._request("POST", "/auth/login",
                             {"username": username, "password": password})
        self.token = data["token"]
        return data

    def register(self, username: str, password: str) -> Any:
        return self._request("POST", "/auth/register",
                             {"username": username, "password": password})

    def logout(self) -> None:
        with suppress(ApiError, NetworkError):
            self._request("POST", "/auth/logout", None)
        self.token = None  # 本地清 token 不受服务端响应影响

    def device_login(self, device_token: str) -> str:
        """本机静默登录：device.token 换 JWT，失败抛 ApiError。"""
        token = self._request("POST", "/auth/device-login",
                              {"deviceToken": device_token})
        self.token = token
        return token

    def create_device_token(self) -> str:
        return self._request("POST", "/auth/device-token", None)

    def me(self) -> dict:
        return self._request("GET", "/users/me")

    # ---------- 分类（科目） ----------
    def category_tree(self) -> Any:
        return self._request("GET", "/categories")

    def create_category(self, name: str, parent_id: str | None = None) -> Any:
        body: dict = {"name": name}
        if parent_id:
            body["parentId"] = parent_id
        return self._request("POST", "/categories", body)

    def rename_category(self, cat_id: str, name: str) -> Any:
        return self._request("PUT", f"/categories/{cat_id}", {"name": name})

    def change_category_status(self, cat_id: str, status: int) -> Any:
        return self._request("PUT", f"/categories/{cat_id}/status?status={status}")

    def delete_category(self, cat_id: str) -> Any:
        return self._request("DELETE", f"/categories/{cat_id}")

    # ---------- 搜题记录 ----------
    def articles(self, page: int = 1, size: int = 100,
                 keyword: str | None = None,
                 category_id: str | None = None) -> dict:
        q: dict = {"page": page, "size": size}
        if keyword:
            q["keyword"] = keyword
        if category_id:
            q["categoryId"] = category_id
        qs = urllib.parse.urlencode(q)
        return self._request("GET", f"/articles?{qs}")

    def delete_article(self, article_id: str) -> Any:
        return self._request("DELETE", f"/articles/{article_id}")

    def move_article(self, article_id: str, category_id: str) -> Any:
        return self._request("PUT", f"/articles/{article_id}",
                             {"categoryId": category_id})

    def create_article(self, body: dict) -> Any:
        """回合结束落库：{title, status, messages[]} → R<ArticleVO>。"""
        return self._request("POST", "/articles", body)

    def push_attachment(self, article_id: str, file_path: str) -> Any:
        """题图上推：multipart POST /sync/push-attachment（走 REST 不直连 DB）。"""
        import mimetypes
        from pathlib import Path
        p = Path(file_path)
        boundary = "----spore" + p.stem
        ctype = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{p.name}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode() + p.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        url = self.base + f"/sync/push-attachment?articleId={article_id}"
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise NetworkError(f"题图上推失败：{e}") from e
        jo = __import__("json").loads(text) if text else {}
        if jo.get("code", -1) != 0:
            raise ApiError(jo.get("code", -1), jo.get("message", "未知错误"))
        return jo.get("data")

    # ---------- 系统 ----------
    def lan_token(self) -> str:
        return self._request("GET", "/auth/lan-token")

    def storage_info(self) -> dict:
        return self._request("GET", "/storage")

    def switch_storage(self, path: str) -> dict:
        return self._request("PUT", "/storage", {"path": path})

    # ---------- HTTP 底座 ----------
    def _request(self, method: str, path: str,
                 body: dict | None = None) -> Any:
        url = self.base + path
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif method in ("POST", "PUT", "PATCH"):
            data = b""  # OkHttp 同款：这些方法必须有 body，GET/DELETE 不许有
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")  # 业务错误也走统一 R 结构
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise NetworkError(f"连不上后端 {self.base}：{e}") from e

        try:
            jo = json.loads(text) if text else {}
        except json.JSONDecodeError as e:
            raise ApiError(-1, f"响应不是 JSON：{text[:120]}") from e
        code = jo.get("code", -1)
        if code != 0:
            raise ApiError(code, jo.get("message", "未知错误"))
        return jo.get("data")
