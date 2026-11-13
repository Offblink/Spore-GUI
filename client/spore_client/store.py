r"""本机数据层：搜题记录与科目都落在 ``%LOCALAPPDATA%\Spore\spore.db``（SQLite）。

2026-11-13 拍板：不再起后端、不做账号、不做手机同步。桌面进程直接读写这张库，
所以这里**没有**用户/角色/权限/同步游标/墓碑——删除即删行。

线程模型：每个线程一条连接（``threading.local``）。界面里的取数仍在 QThread 上跑，
SQLite 连接不能跨线程复用；WAL + busy_timeout 负责并发写。
时间列一律存 **epoch 毫秒**，出参格式化成 ``yyyy-MM-dd HH:mm:ss.SSS``
（与旧接口逐字一致，界面 ``_fmt_stamp`` 切片不用改）。
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 中国无夏令时，固定 +08:00 即可；不用 zoneinfo——Windows 无系统 tzdata，
# 打包后的干净 venv 里 ZoneInfo("Asia/Shanghai") 会直接抛（2026-11-13 实测启动即崩）。
TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
SCHEMA_VERSION = 1          # 结构版本：升版本前自动留一份 spore.db.bak
DEFAULT_DB = Path(
    os.environ.get("SPORE_HOME", Path.home() / "AppData" / "Local" / "Spore")
) / "spore.db"


class StoreError(Exception):
    """本地库读写失败。``code`` 保留旧接口的业务码形状（40001/40401/50000）。"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


SCHEMA = """
CREATE TABLE IF NOT EXISTS category (
  id           TEXT PRIMARY KEY,
  parent_id    TEXT,
  name         TEXT NOT NULL,
  sort_order   INTEGER NOT NULL DEFAULT 0,
  status       INTEGER NOT NULL DEFAULT 1,
  created_time INTEGER NOT NULL,
  update_time  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cat_parent ON category(parent_id);
CREATE INDEX IF NOT EXISTS idx_cat_sort ON category(sort_order, created_time);

CREATE TABLE IF NOT EXISTS article (
  id             TEXT PRIMARY KEY,
  category_id    TEXT,
  title          TEXT NOT NULL DEFAULT '新会话',
  content        TEXT NOT NULL,
  fav            INTEGER NOT NULL DEFAULT 0,
  status         TEXT NOT NULL DEFAULT 'done',
  audit_status   INTEGER NOT NULL DEFAULT 1,
  origin         TEXT NOT NULL DEFAULT 'gui',
  created_time   INTEGER NOT NULL,
  update_time    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_art_cat ON article(category_id);
CREATE INDEX IF NOT EXISTS idx_art_update ON article(update_time);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


def fmt_time(ms: int | None) -> str:
    """epoch 毫秒 → ``yyyy-MM-dd HH:mm:ss.SSS``（Asia/Shanghai）。"""
    if not ms:
        return ""
    dt = datetime.fromtimestamp(ms / 1000, TZ)
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')}.{ms % 1000:03d}"


def _session_id(ms: int) -> str:
    """会话 id：``yyyyMMdd-HHmmssSSS``（与手机端 Session.newId() 同形）。"""
    dt = datetime.fromtimestamp(ms / 1000, TZ)
    return f"{dt.strftime('%Y%m%d-%H%M%S')}{ms % 1000:03d}"


def _category_id(ms: int) -> str:
    """科目 id：时间戳 + ``-`` + 4 位 36 进制随机后缀（撞号概率可忽略）。"""
    suffix = "".join(random.choice("0123456789abcdefghijklmnopqrstuvwxyz")
                     for _ in range(4))
    return f"{_session_id(ms)}-{suffix}"


def _content(messages: list | None) -> str:
    return json.dumps({"messages": messages or []}, ensure_ascii=False)


def _messages(content: str | None) -> list:
    try:
        data = json.loads(content or "{}")
    except ValueError:
        return []
    msgs = data.get("messages") if isinstance(data, dict) else None
    return msgs if isinstance(msgs, list) else []


class Store:
    """搜题记录 / 科目的本地读写。方法名与旧 REST 客户端一致，界面调用点零改写。"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._id_lock = threading.Lock()
        self._last_ms = 0
        self._init_schema()

    def _next_ms(self) -> int:
        """创建行用的时钟：同毫秒连续创建时顺延 1ms，保证 id 与排序唯一。"""
        with self._id_lock:
            ms = max(now_ms(), self._last_ms + 1)
            self._last_ms = ms
            return ms

    # ---------------------------------------------------------------- 连接
    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        with self._init_lock:
            conn = self._connect()
            try:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise StoreError(
                        50000, f"数据库来自更新版本的 Spore（schema {version}）")
                if 0 < version < SCHEMA_VERSION:
                    # 结构要升级：先留一份，坏了还能回滚
                    shutil.copy2(self.path, self.path.with_suffix(".db.bak"))
                with conn:
                    conn.executescript(SCHEMA)
                    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            finally:
                conn.close()

    def close(self) -> None:
        """关掉本线程的连接（测试/退出用）；其他线程的连接随线程结束释放。"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ---------------------------------------------------------------- 查询
    def articles(self, page: int = 1, size: int = 200) -> dict:
        """按 update_time 倒序分页。返回 ``{list,total,page,size}``（旧接口同形）。"""
        page = max(1, int(page or 1))
        size = max(1, min(int(size or 200), 500))
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) FROM article").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM article ORDER BY update_time DESC, created_time DESC"
            " LIMIT ? OFFSET ?", (size, (page - 1) * size)).fetchall()
        names = {r["id"]: r["name"] for r in
                 conn.execute("SELECT id, name FROM category")}
        return {"list": [self._article_dict(r, names) for r in rows],
                "total": total, "page": page, "size": size}

    def article(self, article_id: str) -> dict:
        row = self._conn().execute(
            "SELECT * FROM article WHERE id = ?", (article_id,)).fetchone()
        if row is None:
            raise StoreError(40401, "搜题记录不存在")
        return self._article_dict(row)

    def category_tree(self) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM category ORDER BY sort_order ASC, created_time DESC"
        ).fetchall()
        nodes = {r["id"]: self._category_node(r) for r in rows}
        roots: list[dict] = []
        for r in rows:
            node = nodes[r["id"]]
            parent = nodes.get(r["parent_id"]) if r["parent_id"] else None
            if parent is None or parent is node:
                roots.append(node)          # 悬空/自指的父级按顶层渲染，绝不丢行
            else:
                parent["children"].append(node)
        return roots

    # ---------------------------------------------------------------- 写入
    def create_article(self, body: dict) -> dict:
        body = body or {}
        ms = self._next_ms()
        article_id = _session_id(ms)
        title = str(body.get("title") or "").strip() or "新会话"
        status = str(body.get("status") or "done")
        category_id = self._valid_category(body.get("categoryId"))
        messages = body.get("messages")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO article (id, category_id, title, content, fav, status,"
                " audit_status, origin, created_time, update_time)"
                " VALUES (?, ?, ?, ?, 0, ?, 1, 'gui', ?, ?)",
                (article_id, category_id, title,
                 _content(messages if isinstance(messages, list) else None),
                 status, ms, ms))
        return self.article(article_id)

    def update_article(self, article_id: str, *, title: str | None = None,
                       fav: int | None = None,
                       category_id: str | None = None,
                       messages: list | None = None,
                       status: str | None = None) -> dict:
        """局部更新：``None`` = 不改；``category_id=""`` = 移出科目（置 NULL）。"""
        row = self._conn().execute(
            "SELECT * FROM article WHERE id = ?", (article_id,)).fetchone()
        if row is None:
            raise StoreError(40401, "搜题记录不存在")
        sets: list[str] = []
        args: list[Any] = []
        if title is not None and str(title).strip():
            sets.append("title = ?")
            args.append(str(title).strip())
        if fav is not None:
            sets.append("fav = ?")
            args.append(1 if int(fav) == 1 else 0)
        if category_id is not None:
            sets.append("category_id = ?")
            args.append(self._valid_category(category_id))
        if messages is not None:
            sets.append("content = ?")
            args.append(_content(messages))
        if status is not None:
            sets.append("status = ?")
            args.append(str(status))
        sets.append("update_time = ?")
        args.append(now_ms())
        args.append(article_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE article SET {', '.join(sets)} WHERE id = ?", args)
        return self.article(article_id)

    def delete_article(self, article_id: str) -> None:
        row = self._conn().execute(
            "SELECT id FROM article WHERE id = ?", (article_id,)).fetchone()
        if row is None:
            raise StoreError(40401, "搜题记录不存在")
        with self._conn() as conn:
            conn.execute("DELETE FROM article WHERE id = ?", (article_id,))

    def create_category(self, name: str) -> dict:
        name = str(name or "").strip()
        if not name:
            raise StoreError(40001, "科目名不能为空")
        ms = self._next_ms()
        cat_id = _category_id(ms)
        with self._conn() as conn:
            order = conn.execute("SELECT COUNT(*) FROM category").fetchone()[0]
            conn.execute(
                "INSERT INTO category (id, parent_id, name, sort_order, status,"
                " created_time, update_time) VALUES (?, NULL, ?, ?, 1, ?, ?)",
                (cat_id, name, order, ms, ms))
        return {"id": cat_id, "parentId": None, "name": name,
                "sortOrder": order, "status": 1, "children": []}

    def rename_category(self, cat_id: str, name: str) -> None:
        name = str(name or "").strip()
        if not name:
            raise StoreError(40001, "科目名不能为空")
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE category SET name = ?, update_time = ? WHERE id = ?",
                (name, now_ms(), cat_id))
            if cur.rowcount == 0:
                raise StoreError(40401, "科目不存在")

    def delete_category(self, cat_id: str) -> None:
        """删科目：其下会话回未分组，子科目升为顶层（会话本身不动）。"""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM category WHERE id = ?", (cat_id,))
            if cur.rowcount == 0:
                raise StoreError(40401, "科目不存在")
            conn.execute(
                "UPDATE article SET category_id = NULL, update_time = ?"
                " WHERE category_id = ?", (now_ms(), cat_id))
            conn.execute("UPDATE category SET parent_id = NULL WHERE parent_id = ?",
                         (cat_id,))

    # ---------------------------------------------------------------- 内部
    def _valid_category(self, category_id: str | None) -> str | None:
        """不存在/空串 → None（回未分组），不整单拒收。"""
        cid = str(category_id or "").strip()
        if not cid:
            return None
        row = self._conn().execute(
            "SELECT id FROM category WHERE id = ?", (cid,)).fetchone()
        return cid if row is not None else None

    def _article_dict(self, row: sqlite3.Row,
                      cat_names: dict[str, str] | None = None) -> dict:
        name = None
        if row["category_id"]:
            if cat_names is None:
                hit = self._conn().execute(
                    "SELECT name FROM category WHERE id = ?",
                    (row["category_id"],)).fetchone()
                name = hit["name"] if hit is not None else None
            else:
                name = cat_names.get(row["category_id"])
        return {
            "id": row["id"],
            "categoryId": row["category_id"],
            "categoryName": name,
            "title": row["title"],
            "fav": int(row["fav"] or 0),
            "status": row["status"],
            "auditStatus": int(row["audit_status"] or 1),
            "origin": row["origin"],
            "messages": _messages(row["content"]),
            "createdTime": fmt_time(row["created_time"]),
            "updateTime": fmt_time(row["update_time"]),
        }

    @staticmethod
    def _category_node(row: sqlite3.Row) -> dict:
        return {"id": row["id"], "parentId": row["parent_id"], "name": row["name"],
                "sortOrder": row["sort_order"], "status": row["status"],
                "children": []}
