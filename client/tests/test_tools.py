"""tools.py 契约测试——不起网络：URL 解码/相关性闸/引擎链计划是纯函数。

钉住的都是 Fungi §71 移植关键点：ddg 只解码一次（二次会解坏 %20）、
unbing base64url、诱饵页闸、代理定序。
"""

import urllib.parse

from spore_client.answer.tools import (
    clean,
    ddg_target,
    decode_entities,
    format_results,
    relevant,
    search_plan,
    set_search_proxy,
    truncate_middle,
    unbing,
)

# ---------- 引擎链定序（代理字段） ----------

def test_plan_no_proxy_bing_only():
    # 留空 = 没代理 → 只走 bing（ddg 直连白等一个超时）
    set_search_proxy("")
    assert search_plan() == ["bing"]


def test_plan_with_proxy_full_chain():
    set_search_proxy("127.0.0.1:7897")
    assert search_plan() == ["duckduckgo", "bing", "brave"]


def test_plan_explicit_arg_beats_global():
    set_search_proxy("")
    assert search_plan("x:1") == ["duckduckgo", "bing", "brave"]


# ---------- ddg 跳转解码：只解一次（回归钉子） ----------

def test_ddg_target_decodes_once():
    href = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa"
    assert ddg_target(href) == "https://example.com/a"


def test_ddg_target_keeps_percent20_intact():
    # 二次 unquote 会把 URL 里合法的 %20 解成空格（Fungi 踩过的坑）——只解一次
    href = "https://example.com/search?q=hello%20world&r=1"
    assert ddg_target(href) == href  # 无 uddg 参数时原样返回且不被解坏
    wrapped = ("https://duckduckgo.com/l/?uddg="
               + urllib.parse.quote("https://example.com/a%20b", safe=""))
    assert ddg_target(wrapped) == "https://example.com/a%20b"


def test_ddg_target_protocol_relative_and_garbage():
    assert ddg_target("//duckduckgo.com/l/?uddg=https%3A%2F%2Fx.cn") == "https://x.cn"
    assert ddg_target("not a url") == "not a url"  # 非法 URL 原样


# ---------- unbing base64url ----------

def test_unbing_decodes_base64url():
    # https://x.cn/path → base64url（-/_ 替换 + padding）
    raw = "https://www.bing.com/ck/a?!&p=xxx&u=a1aHR0cHM6Ly9leGFtcGxlLmNvbQ"
    assert unbing(raw) == "https://example.com"


def test_unbing_plain_url_untouched():
    u = "https://cn.bing.com/search?q=java"
    assert unbing(u) == u


def test_unbing_bad_base64_returns_original():
    u = "https://bing.com/ck/a?u=a1!!!!notbase64"
    assert unbing(u) == u


# ---------- 相关性闸（诱饵页判定） ----------

def test_relevant_needs_real_words():
    assert relevant("deepseek v4 发布时间", "deepseek 发布 v4 模型于今日") is True
    # 查询实词全不在结果里 → 诱饵页，拒收
    assert relevant("deepseek release date", "totally unrelated cooking recipes") is False


def test_relevant_short_words_and_noise_ignored():
    # 虚词/短词（<4字符或 NOISE_WORDS）不构成证据；全被过滤掉就直接放行
    assert relevant("the a is", "anything at all") is True
    assert relevant("how does it work", "a page about how does it work") is True
    # 过滤后还剩实词 work → 结果必须含 work（不含 = 诱饵页）
    assert relevant("how does it work", "some generic page about nothing") is False


def test_relevant_cjk_query_matches_substring():
    # 中文查询整段成 token，要求结果原文出现该段（注释原文语义）
    assert relevant("软件工程定义", "软件工程定义如下……") is True
    assert relevant("软件工程定义", "软件工程的定义如下……") is False  # 中间夹字≠连续子串
    assert relevant("软件工程定义", "完全无关的内容") is False


# ---------- 文本工具 ----------

def test_truncate_middle_keeps_both_ends():
    t = "A" * 100 + "MID" + "B" * 100
    out = truncate_middle(t, 50)
    assert out.startswith("A" * 25)
    assert out.endswith("B" * 25)
    assert "MID" not in out
    assert "truncated" in out
    assert truncate_middle("short", 50) == "short"  # 不超不截


def test_decode_entities_named_and_numeric():
    assert decode_entities("a&amp;b&lt;c&#65;d&#x42;") == "a&b<cAdB"
    assert decode_entities("&hellip;&mdash;") == "…—"
    assert decode_entities("&unknownent;") == "&unknownent;"  # 不认识的原样


def test_clean_strips_tags_and_collapses():
    assert clean("<b>Title</b>\n\n  text") == "Title text"


def test_format_results_numbered_layout():
    out = format_results([
        {"title": "T1", "url": "https://a.cn", "snippet": "s1"},
        {"title": "T2", "url": "https://b.cn", "snippet": ""},
    ])
    assert "1. T1\n   https://a.cn\n   s1" in out
    # 无 snippet 的末条不留空行占位，输出以 URL 收尾
    assert out.endswith("2. T2\n   https://b.cn")
