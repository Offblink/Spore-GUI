"""同步引擎：先推后拉、双游标、LWW、墓碑、题图（假客户端，不碰网络）。"""

from __future__ import annotations

from spore_client import sync_engine
from spore_client.store import Store, now_ms
from spore_client.sync_engine import SyncEngine


class FakeClient:
    def __init__(self, me=None):
        self.me_row = me or {"id": 1, "nickname": "演示"}
        self.pushes: list[tuple[int, int]] = []
        self.pull_script: list[dict] = []
        self.uploads: list[tuple[str, str]] = []
        self.downloads: list[str] = []
        self.blob = b"jpg"

    def me(self):
        return dict(self.me_row)

    def push(self, categories, articles):
        self.pushes.append((len(categories), len(articles)))
        return [{"id": (categories or articles)[0]["id"], "accepted": True}]

    def pull(self, cursor, limit=200):
        if self.pull_script:
            return self.pull_script.pop(0)
        return {"categories": [], "articles": [], "nextCursor": cursor}

    def push_attachment(self, article_id, path):
        self.uploads.append((article_id, str(path)))
        return f"2026/{article_id}.jpg"

    def pull_attachment(self, rel):
        self.downloads.append(rel)
        return self.blob


def make_store(tmp_path):
    return Store(tmp_path / "spore.db")


def test_push_categories_before_articles_then_attachments(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    img = tmp_path / "shot.jpg"
    img.write_bytes(b"jpg")
    store.create_category("数学")
    art = store.create_article({"title": "会话",
                                "messages": [{"role": "user", "imagePath": str(img)}]})
    client = FakeClient()

    result = SyncEngine(store, client).run()

    kinds = [(c, a) for c, a in client.pushes]
    assert kinds[0][0] == 1 and kinds[0][1] == 0        # 科目先落
    assert kinds[1][0] == 0 and kinds[1][1] == 1        # 会话随后
    assert client.uploads == [(art["id"], str(img))]    # 题图殿后
    assert result["up"] == 2 and result["images"] == 1
    # 第二轮：游标已过，什么都不再推
    before = len(client.pushes)
    client.uploads.clear()
    SyncEngine(store, client).run()
    assert len(client.pushes) == before
    assert client.uploads == []


def test_pull_applies_rows_and_prevents_echo(tmp_path):
    store = make_store(tmp_path)
    server_ts = now_ms() - 60_000
    client = FakeClient()
    client.pull_script = [{
        "categories": [{"id": "c1", "name": "物理", "sortOrder": 0,
                        "status": 1, "created": server_ts, "updated": server_ts,
                        "deleted": 0}],
        "articles": [{"id": "a1", "categoryId": "c1", "title": "来自手机",
                      "messages": [{"role": "user", "content": "hi"}],
                      "fav": 1, "status": "done", "created": server_ts,
                      "updated": server_ts, "deleted": 0}],
        "nextCursor": server_ts,
    }]

    result = SyncEngine(store, client).run()

    assert result["down"] == 2
    arts = store.articles()["list"]
    assert [a["id"] for a in arts] == ["a1"]
    assert arts[0]["categoryName"] == "物理"
    assert store.meta("pull_cursor") == str(server_ts)
    # 套用服务端行 → pushCursor 抬到服务端时间戳（否则下一轮回声重推）
    assert store.meta("push_cursor") == str(server_ts)
    client.pushes.clear()
    SyncEngine(store, client).run()
    assert client.pushes == []


def test_server_clock_ahead_does_not_move_push_cursor(tmp_path):
    store = make_store(tmp_path)
    future = now_ms() + 3_600_000
    client = FakeClient()
    client.pull_script = [{
        "categories": [],
        "articles": [{"id": "a9", "title": "未来行",
                      "messages": [], "updated": future, "deleted": 0}],
        "nextCursor": future,
    }]

    SyncEngine(store, client).run()

    assert store.article_row("a9") is not None
    assert store.meta("push_cursor") in ("", "0")   # 不越过本机墙上时间


def test_delete_is_pushed_as_tombstone(tmp_path):
    store = make_store(tmp_path)
    art = store.create_article({"title": "待删"})
    client = FakeClient()
    SyncEngine(store, client).run()                 # 先上行一次
    store.delete_article(art["id"])

    seen = {}

    def push(categories, articles):
        seen["deleted"] = [a["deleted"] for a in articles if a["id"] == art["id"]]
        return []

    client.push = push
    SyncEngine(store, client).run()
    assert seen["deleted"] == [1]


def test_pull_tombstone_hides_local_row(tmp_path):
    store = make_store(tmp_path)
    art = store.create_article({"title": "本机"})
    ts = now_ms() + 1000          # 服务端墓碑必须比本地行新，LWW 才会套用
    client = FakeClient()
    client.pull_script = [{
        "categories": [],
        "articles": [{"id": art["id"], "title": "本机", "messages": [],
                      "updated": ts, "deleted": 1}],
        "nextCursor": ts,
    }]
    SyncEngine(store, client).run()
    assert store.articles()["total"] == 0


def test_account_switch_resets_cursors(tmp_path):
    store = make_store(tmp_path)
    store.set_meta("uid", "1")
    store.set_meta("push_cursor", "9999999999999")
    store.set_meta("pull_cursor", "9999999999999")
    store.create_article({"title": "本地"})
    client = FakeClient(me={"id": 2, "nickname": "另一个人"})

    SyncEngine(store, client).run()

    assert store.meta("uid") == "2"
    assert store.meta("push_cursor") != "9999999999999"
    assert store.meta("pull_cursor") in ("", "0")


def test_attachment_download_repoints_missing_image(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    captures = tmp_path / "captures"
    monkeypatch.setattr(sync_engine, "CAPTURE_DIR", captures)
    ts = now_ms() - 1000
    client = FakeClient()
    client.pull_script = [{
        "categories": [],
        "articles": [{"id": "a2", "title": "手机拍的",
                      "messages": [{"role": "user", "imagePath": "/phone/cap.jpg"}],
                      "attachmentPath": "2026/a2.jpg", "updated": ts, "deleted": 0}],
        "nextCursor": ts,
    }]

    SyncEngine(store, client).run()

    target = captures / "att_a2.jpg"
    assert target.read_bytes() == b"jpg"
    image_paths = [m.get("imagePath")
                   for m in store.article_row("a2")["messages"]]
    assert image_paths == [str(target)]
    assert client.downloads == ["2026/a2.jpg"]
