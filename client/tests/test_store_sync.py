"""数据层新契约：schema v2 迁移、软删墓碑、sync_meta、云端行套用（LWW）。"""

from __future__ import annotations

import sqlite3

from spore_client.store import Store

V1_SCHEMA = """
CREATE TABLE category (
  id TEXT PRIMARY KEY, parent_id TEXT, name TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0, status INTEGER NOT NULL DEFAULT 1,
  created_time INTEGER NOT NULL, update_time INTEGER NOT NULL);
CREATE TABLE article (
  id TEXT PRIMARY KEY, category_id TEXT, title TEXT NOT NULL DEFAULT '新会话',
  content TEXT NOT NULL, fav INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'done', audit_status INTEGER NOT NULL DEFAULT 1,
  origin TEXT NOT NULL DEFAULT 'gui',
  created_time INTEGER NOT NULL, update_time INTEGER NOT NULL);
"""


def make_v1_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(V1_SCHEMA)
    conn.execute("INSERT INTO category VALUES ('c1', NULL, '旧科目', 0, 1, 1000, 1000)")
    conn.execute("INSERT INTO article VALUES ('a1', 'c1', '旧会话',"
                 " '{\"messages\":[{\"role\":\"user\",\"content\":\"x\"}]}',"
                 " 1, 'done', 1, 'gui', 1000, 1000)")
    conn.execute("PRAGMA user_version = 1")
    commit_and_close(conn)


def commit_and_close(conn):
    conn.commit()
    conn.close()


def test_v1_db_migrates_to_v2_keeping_rows(tmp_path):
    db = tmp_path / "spore.db"
    make_v1_db(db)

    store = Store(db)

    assert db.with_suffix(".db.bak").exists()       # 升级前留了回滚副本
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(article)")}
    conn.close()
    assert {"deleted", "attachment_path"} <= cols
    assert store.articles()["total"] == 1
    assert store.category_tree()[0]["name"] == "旧科目"
    assert store.meta("push_cursor") == ""          # 老库没有水位


def test_soft_delete_keeps_tombstone_but_hides_row(tmp_path):
    store = Store(tmp_path / "spore.db")
    art = store.create_article({"title": "要删"})
    store.delete_article(art["id"])

    assert store.articles()["total"] == 0
    tomb = store.changed_articles(0)
    assert [r["id"] for r in tomb] == [art["id"]]
    assert tomb[0]["deleted"] == 1


def test_delete_category_leaves_articles_ungrouped(tmp_path):
    store = Store(tmp_path / "spore.db")
    cat = store.create_category("数学")
    art = store.create_article({"title": "会话", "categoryId": cat["id"]})
    store.delete_category(cat["id"])

    assert store.category_tree() == []
    row = store.articles()["list"][0]
    assert row["id"] == art["id"] and row["categoryId"] is None


def test_meta_roundtrip_and_cursor_reset(tmp_path):
    store = Store(tmp_path / "spore.db")
    store.set_meta("pull_cursor", 42)
    store.set_meta("push_cursor", "43")
    assert store.meta("pull_cursor") == "42"
    store.reset_sync_cursors()
    assert store.meta("pull_cursor") == ""
    assert store.meta("push_cursor") == ""


def test_apply_article_lww_and_category_binding(tmp_path):
    store = Store(tmp_path / "spore.db")
    store.apply_category({"id": "c1", "name": "物理", "sortOrder": 0,
                          "status": 1, "created": 100, "updated": 100,
                          "deleted": 0})
    assert store.apply_article({"id": "a1", "categoryId": "c1",
                                "title": "手机行", "messages": [],
                                "fav": 1, "status": "done",
                                "created": 100, "updated": 200, "deleted": 0})
    row = store.articles()["list"][0]
    assert row["title"] == "手机行" and row["fav"] == 1
    assert row["categoryName"] == "物理"

    # 服务端时间戳不新于本地 → 拒收（同毫秒保留本地）
    assert not store.apply_article({"id": "a1", "title": "旧行",
                                    "messages": [], "updated": 200})
    assert store.articles()["list"][0]["title"] == "手机行"


def test_apply_article_drops_dangling_category(tmp_path):
    store = Store(tmp_path / "spore.db")
    assert store.apply_article({"id": "a1", "categoryId": "ghost",
                                "title": "悬空", "messages": [],
                                "updated": 300, "deleted": 0})
    assert store.articles()["list"][0]["categoryId"] is None
