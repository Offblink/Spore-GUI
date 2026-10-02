"""settings_store 契约：文件值生效 / 环境变量赢 / MV3 钳制 / api_key 永不落盘。

PATH 是模块级常量（主线也可能读），测试里 monkeypatch 到 tmp 隔离真实
%LOCALAPPDATA%\\Spore\\ui_settings.json。
"""

import pytest

from spore_client import settings_store
from spore_client.answer.settings import LlmSettings, load_from_env

ENV_KEYS = (
    "SPORE_ENDPOINT",
    "SPORE_MODEL",
    "SPORE_MAX_TOOL_ROUNDS",
    "SPORE_SEARCH_PROXY",
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "PATH", tmp_path / "ui_settings.json")
    for key in ENV_KEYS:                    # 测试环境不许残留真环境变量
        monkeypatch.delenv(key, raising=False)
    return settings_store


# ---------- 读写 ----------

def test_read_missing_file_returns_empty(store):
    assert store.read() == {}               # 缺文件不抛，主线用 .get 带默认


def test_read_corrupt_file_returns_empty(store):
    store.PATH.write_text("{oops not json", encoding="utf-8")
    assert store.read() == {}               # 损坏不抛


def test_write_read_roundtrip(store):
    store.write({"endpoint": "https://x/e", "proxy": "1.2.3.4:5",
                 "autoVerify": False})
    assert store.read() == {
        "endpoint": "https://x/e", "proxy": "1.2.3.4:5", "autoVerify": False,
    }


def test_api_key_never_persisted(store):
    # 红线：key 只在环境变量 —— 就算调用方误塞进来，白名单也不许它落盘
    store.write({"endpoint": "https://x/e", "api_key": "sk-secret",
                 "apiKey": "sk-2", "proxy": "1.2.3.4:5"})
    raw = store.PATH.read_text(encoding="utf-8")
    assert "api_key" not in raw and "apiKey" not in raw
    assert "sk-secret" not in raw
    assert store.read() == {"endpoint": "https://x/e", "proxy": "1.2.3.4:5"}


# ---------- apply_to_llm ----------

def test_file_values_apply_to_llm(store):
    store.write({"endpoint": "https://file/e", "model": "file-model",
                 "maxToolRounds": 3, "historyLimit": 20,
                 "proxy": "127.0.0.1:7897",
                 "fastNoThink": False, "autoVerify": False})
    llm = store.apply_to_llm(LlmSettings())
    assert llm.endpoint == "https://file/e"
    assert llm.model == "file-model"
    assert llm.max_tool_rounds == 3
    assert llm.history_limit == 20
    assert llm.proxy == "127.0.0.1:7897"
    assert llm.fast_no_think is False
    assert llm.auto_verify is False
    assert llm.api_key == ""               # 绝不碰 key


def test_env_wins_over_file(store, monkeypatch):
    store.write({"endpoint": "https://file/e", "model": "file-model",
                 "maxToolRounds": 3, "proxy": "1.1.1.1:1",
                 "autoVerify": False})
    monkeypatch.setenv("SPORE_ENDPOINT", "https://env/e")
    monkeypatch.setenv("SPORE_MODEL", "env-model")
    monkeypatch.setenv("SPORE_MAX_TOOL_ROUNDS", "7")
    monkeypatch.setenv("SPORE_SEARCH_PROXY", "9.9.9.9:9")
    # 主线真实路径：load_from_env 先按 env 构好，apply 不许用文件值覆盖 env
    llm = store.apply_to_llm(load_from_env())
    assert llm.endpoint == "https://env/e"     # 四个 env 字段全赢
    assert llm.model == "env-model"
    assert llm.max_tool_rounds == 7
    assert llm.proxy == "9.9.9.9:9"
    assert llm.auto_verify is False            # 文件独有字段仍生效


def test_env_partial_only_endpoint_wins(store, monkeypatch):
    store.write({"endpoint": "https://file/e", "model": "file-model",
                 "proxy": "1.1.1.1:1"})
    monkeypatch.setenv("SPORE_ENDPOINT", "https://env/e")
    llm = store.apply_to_llm(load_from_env())
    assert llm.endpoint == "https://env/e"
    assert llm.model == "file-model"           # 没设 env 的字段用文件值
    assert llm.proxy == "1.1.1.1:1"


def test_empty_file_leaves_llm_untouched(store):
    llm = store.apply_to_llm(LlmSettings())
    assert llm.endpoint and llm.model          # 还是默认值
    assert llm.max_tool_rounds == 5


# ---------- MV3 钳制（options.js:43-45） ----------

def test_max_tool_rounds_clamped_0_10(store):
    store.write({"maxToolRounds": 99})
    assert store.apply_to_llm(LlmSettings()).max_tool_rounds == 10
    store.write({"maxToolRounds": -5})
    assert store.apply_to_llm(LlmSettings()).max_tool_rounds == 0
    store.write({"maxToolRounds": "junk"})
    assert store.apply_to_llm(LlmSettings()).max_tool_rounds == 5  # 设错保持默认


def test_history_limit_clamped_2_50_fallback_10(store):
    store.write({"historyLimit": 99})
    assert store.apply_to_llm(LlmSettings()).history_limit == 50
    store.write({"historyLimit": -3})
    assert store.apply_to_llm(LlmSettings()).history_limit == 2
    store.write({"historyLimit": "junk"})      # MV3 Number(x)||10 → 10
    assert store.apply_to_llm(LlmSettings()).history_limit == 10
    store.write({"historyLimit": 0})
    assert store.apply_to_llm(LlmSettings()).history_limit == 10
