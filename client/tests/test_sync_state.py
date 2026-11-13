"""连接凭据文件：白名单落盘、原子写、清空；token 只在这一个文件里。"""

import json

from spore_client import sync_state


def test_save_filters_unknown_keys_and_roundtrips(tmp_path, monkeypatch):
    path = tmp_path / "sync_state.json"
    monkeypatch.setattr(sync_state, "PATH", path)

    sync_state.save({"api": "http://h:19080/api", "token": "jwt",
                     "username": "demo", "nick": "演示", "uid": "7",
                     "password": "should-not-persist"})

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "password" not in raw
    assert raw["token"] == "jwt"
    assert sync_state.load()["uid"] == "7"


def test_clear_wipes_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_state, "PATH", tmp_path / "s.json")
    sync_state.save({"api": "h", "token": "t"})
    sync_state.clear()
    assert sync_state.load() == {}


def test_broken_file_reads_as_empty(tmp_path, monkeypatch):
    path = tmp_path / "s.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(sync_state, "PATH", path)
    assert sync_state.load() == {}
