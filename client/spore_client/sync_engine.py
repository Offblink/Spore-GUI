"""双向同步引擎：游标增量 + LWW + 墓碑 + 题图（对齐 Spore-Cloud ``SyncService``）。

一条铁律：**pull 不许碰 pushCursor**。pull 只把「套用服务端行」这一刻的
``server.updated`` 抬进 pushCursor（{:meth:`_mark_clean`}）——那行内容本就来自
服务端、不是本地改动；不抬的话下一轮会把它当新改动重推（回声打转，上/下行永不归 0）。
抬之前先比本机时钟：服务端时钟超前时**不抬**，否则会把之后的本地改动（= 本机时钟）
静默吞掉。

上行顺序（都有原因，别调）：科目 → 会话分块 → 题图殿后。题图先于行推会让
服务器 ``bindAttachment`` 把 ``update_time`` 抬到服务端时钟，行的 LWW 键（本地
编辑时刻）严格小于它 → 必被拒 + 下一轮 pull 把服务端旧行回灌。
"""

from __future__ import annotations

from pathlib import Path

from .capture import CAPTURE_DIR
from .log import get_logger
from .store import Store, now_ms
from .sync_client import SyncClient

LOG = get_logger()

PULL_LIMIT = 200
PUSH_CHUNK = 100


class SyncEngine:
    def __init__(self, store: Store, client: SyncClient):
        self.store = store
        self.client = client

    # ---------------------------------------------------------------- 入口
    def run(self) -> dict:
        """跑一轮（先推后拉）。异常原样抛给调用方（NetworkError / SyncError）。"""
        me = self.client.me()
        uid = str(me.get("id") or "")
        if uid and self.store.meta("uid") != uid:
            # 换账号/换服务器：旧水位会把新账号的存量行永久跳过
            self.store.reset_sync_cursors()
            self.store.set_meta("uid", uid)
        up, images = self._push()
        down = self._pull()
        self.store.set_meta("last_sync_at", now_ms())
        return {"up": up, "down": down, "images": images,
                "uid": uid, "nick": str(me.get("nickname") or "")}

    # ---------------------------------------------------------------- 上行
    def _push(self) -> tuple[int, int]:
        cursor = int(self.store.meta("push_cursor", "0") or 0)
        cursor, cats_up = self._push_categories(cursor)
        cursor, arts = self._push_articles(cursor)
        images = self._push_images(arts)
        return cats_up + len(arts), images

    def _push_categories(self, cursor: int) -> tuple[int, int]:
        sent = 0
        while True:
            rows = self.store.changed_categories(cursor, PUSH_CHUNK)
            if not rows:
                break
            self.client.push(rows, [])
            cursor = max(cursor, max(int(r["updated"]) for r in rows))
            self.store.set_meta("push_cursor", cursor)
            sent += len(rows)
            if len(rows) < PUSH_CHUNK:
                break
        return cursor, sent

    def _push_articles(self, cursor: int) -> tuple[int, list[dict]]:
        sent: list[dict] = []
        while True:
            rows = self.store.changed_articles(cursor, PUSH_CHUNK)
            if not rows:
                break
            self.client.push([], rows)
            cursor = max(cursor, max(int(r["updated"]) for r in rows))
            self.store.set_meta("push_cursor", cursor)
            sent.extend(rows)
            if len(rows) < PUSH_CHUNK:
                break
        return cursor, sent

    def _push_images(self, rows: list[dict]) -> int:
        """行先落、图后补：只推「本地有图、服务端还没记路径」的会话。"""
        done = 0
        for row in rows:
            if int(row.get("deleted") or 0):
                continue
            local = self.store.article_row(row["id"])
            if local is None or local["attachment_path"]:
                continue
            path = _image_of(local["messages"])
            if path is None:
                continue
            try:
                rel = self.client.push_attachment(row["id"], path)
            except Exception as e:  # 单张图失败不拖垮整轮，下轮再试
                LOG.warning("push attachment failed for %s: %s", row["id"], e)
                continue
            if rel:
                self.store.set_attachment_path(row["id"], rel)
                done += 1
        return done

    # ---------------------------------------------------------------- 下行
    def _pull(self) -> int:
        cursor = int(self.store.meta("pull_cursor", "0") or 0)
        applied = 0
        while True:
            data = self.client.pull(cursor, PULL_LIMIT)
            cats = data.get("categories") or []
            arts = data.get("articles") or []
            nxt = int(data.get("nextCursor") or 0)
            if not cats and not arts:
                break
            for row in cats:
                if self.store.apply_category(row):
                    applied += 1
                    self._mark_clean(int(row.get("updated") or 0))
            for row in arts:
                if self.store.apply_article(row):
                    applied += 1
                    self._mark_clean(int(row.get("updated") or 0))
                    self._pull_image(row)
            new_cursor = max(cursor, nxt)
            if new_cursor <= cursor:
                break                        # 服务端没给前进水位：收工，别死循环
            cursor = new_cursor
            self.store.set_meta("pull_cursor", cursor)
        return applied

    def _pull_image(self, row: dict) -> None:
        rel = str(row.get("attachmentPath") or "")
        if not rel or int(row.get("deleted") or 0):
            return
        local = self.store.article_row(row["id"])
        if local is None:
            return
        if _image_of(local["messages"]) is not None:
            return                            # 本地已有图，不用拉
        try:
            blob = self.client.pull_attachment(rel)
        except Exception as e:
            LOG.warning("pull attachment failed for %s: %s", row["id"], e)
            return
        if not blob:
            return
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(rel).suffix or ".jpg"
        target = CAPTURE_DIR / f"att_{row['id']}{suffix}"
        target.write_bytes(blob)
        self.store.repoint_image(row["id"], str(target))

    def _mark_clean(self, server_updated: int) -> None:
        if server_updated <= 0:
            return
        if server_updated > now_ms():
            return                            # 服务端时钟超前：抬了就吞掉本地改动
        cursor = int(self.store.meta("push_cursor", "0") or 0)
        if server_updated > cursor:
            self.store.set_meta("push_cursor", server_updated)


def _image_of(messages: list) -> Path | None:
    """消息里第一张本机存在的题图（与手机端 ShotPolicy 同判据）。"""
    for m in messages:
        if not isinstance(m, dict):
            continue
        raw = str(m.get("imagePath") or "")
        if raw and Path(raw).is_file():
            return Path(raw)
    return None
