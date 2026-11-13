"""本机 SQLite 存储：界面读写的唯一数据源（无服务端、无同步）。

钉住用户可见的行为：列表顺序/分页、默认值、科目树与删科目解绑、
局部更新的「None=不改」语义、时间戳格式与持久化。
"""

from __future__ import annotations

import re
import sqlite3
import threading

import pytest

from spore_client.store import Store, StoreError, fmt_time


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "spore.db")
    yield s
    s.close()


def test_empty_store_returns_page_shape(store):
    assert store.articles() == {"list": [], "total": 0, "page": 1, "size": 200}


def test_create_article_defaults_and_id(store):
    art = store.create_article({"messages": [{"role": "user", "text": "题"}]})
    assert re.fullmatch(r"\d{8}-\d{6}\d{3}", art["id"])
    assert art["title"] == "新会话"
    assert art["status"] == "done"
    assert art["fav"] == 0
    assert art["auditStatus"] == 1
    assert art["categoryId"] is None
    assert art["messages"] == [{"role": "user", "text": "题"}]
    assert art["createdTime"] == art["updateTime"]


def test_blank_title_falls_back_to_default(store):
    art = store.create_article({"title": "   ", "messages": []})
    assert art["title"] == "新会话"


def test_update_partial_semantics(store):
    art = store.create_article({"title": "旧", "messages": []})
    ms = art["updateTime"]
    upd = store.update_article(art["id"], title="新", fav=1)
    assert upd["title"] == "新" and upd["fav"] == 1
    assert upd["status"] == "done"                  # None = 不改
    assert upd["updateTime"] >= ms
    # 空标题不算改名（与旧接口一致）
    same = store.update_article(art["id"], title="  ")
    assert same["title"] == "新"


def test_messages_roundtrip_unicode_and_nesting(store):
    msgs = [{"role": "assistant", "kind": "answer", "ans": "答案",
             "tools": ["检索 x"], "nested": {"a": [1, 2]}}]
    art = store.create_article({"messages": msgs})
    assert store.article(art["id"])["messages"] == msgs


def test_unknown_article_raises_not_found(store):
    with pytest.raises(StoreError) as ei:
        store.article("nope")
    assert ei.value.code == 40401
    with pytest.raises(StoreError):
        store.update_article("nope", title="x")
    with pytest.raises(StoreError):
        store.delete_article("nope")


def test_delete_article_is_hard_delete(store):
    art = store.create_article({"messages": []})
    store.delete_article(art["id"])
    assert store.articles()["total"] == 0
    with pytest.raises(StoreError):
        store.article(art["id"])


def test_category_tree_order_and_rename(store):
    a = store.create_category("数学")
    store.create_category("物理")
    assert [c["name"] for c in store.category_tree()] == ["数学", "物理"]
    store.rename_category(a["id"], "高数")
    assert store.category_tree()[0]["name"] == "高数"
    with pytest.raises(StoreError):
        store.rename_category(a["id"], "   ")
    with pytest.raises(StoreError):
        store.rename_category("missing", "x")


def test_move_into_and_out_of_category(store):
    cat = store.create_category("软件测试")
    art = store.create_article({"messages": []})
    moved = store.update_article(art["id"], category_id=cat["id"])
    assert moved["categoryId"] == cat["id"]
    assert moved["categoryName"] == "软件测试"
    out = store.update_article(art["id"], category_id="")
    assert out["categoryId"] is None and out["categoryName"] is None


def test_unknown_category_is_ignored_not_rejected(store):
    art = store.create_article({"messages": [], "categoryId": "ghost"})
    assert art["categoryId"] is None
    upd = store.update_article(art["id"], category_id="ghost")
    assert upd["categoryId"] is None


def test_delete_category_unbinds_articles(store):
    cat = store.create_category("临时科目")
    art = store.create_article({"messages": [], "categoryId": cat["id"]})
    store.delete_category(cat["id"])
    assert store.category_tree() == []
    assert store.article(art["id"])["categoryId"] is None


def test_pagination_and_order(store):
    ids = [store.create_article({"title": f"第{i}题", "messages": []})["id"]
           for i in range(5)]
    # 同毫秒创建时按 created_time 再兜一层；最后一条必须排最前
    page1 = store.articles(page=1, size=2)
    page3 = store.articles(page=3, size=2)
    assert page1["total"] == 5 and len(page1["list"]) == 2
    assert len(page3["list"]) == 1
    seen = {r["id"] for r in page1["list"]} | {
        r["id"] for r in store.articles(page=2, size=2)["list"]} | {
        r["id"] for r in page3["list"]}
    assert seen == set(ids)
    assert store.articles()["list"][0]["id"] == ids[-1]


def test_time_format_matches_legacy(store):
    art = store.create_article({"messages": []})
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}",
                        art["updateTime"])
    assert fmt_time(0) == ""


def test_corrupt_content_does_not_crash(store, tmp_path):
    art = store.create_article({"messages": []})
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE article SET content = ? WHERE id = ?",
                     ("not json", art["id"]))
    assert store.article(art["id"])["messages"] == []


def test_persists_across_reopen(tmp_path):
    first = Store(tmp_path / "spore.db")
    art = first.create_article({"title": "持久化", "messages": []})
    first.close()
    second = Store(tmp_path / "spore.db")
    try:
        assert second.article(art["id"])["title"] == "持久化"
    finally:
        second.close()


def test_concurrent_reader_thread(store):
    store.create_article({"title": "并发", "messages": []})
    got: list = []

    def read():
        got.append(store.articles()["total"])
        store.close()

    t = threading.Thread(target=read)
    t.start()
    t.join(timeout=5)
    assert got == [1]


def test_refuses_database_from_newer_version(tmp_path):
    path = tmp_path / "newer.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 99")
    with pytest.raises(StoreError):
        Store(path)
