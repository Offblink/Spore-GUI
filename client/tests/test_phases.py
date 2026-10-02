"""MV3 tests/answer.test.mjs 的逐条对拍——语义权威是那份，这边是它的 Python 镜像。

原测试文件头注释翻译：
「起因是用户实测截图：第17题 A（对）和…故该说法错误 并排出现，
 而 <<ok>> 守卫把核实整个跳过了。极性判定误伤的代价只是多跑一次核实，
 但漏判会直接把矛盾答案端给用户——这里把两侧都钉死。」
"""

from spore_client.answer.phases import (
    contradicts,
    is_self_certain,
    parse_phase_a,
    parse_phase_b,
)

WHY_BAD = "制定软件质量计划属于SQA活动中的计划与实施范畴，故该说法错误。"


# ---------- contradicts：初答自检 ----------

def test_answer_line_fights_conclusion_detected():
    # 用户截图里的那道判断题（原测试第 1 条）
    assert contradicts("A（对）", WHY_BAD) is True
    assert contradicts("A（对）", "A 不对，应选 B。") is True
    assert contradicts("错", "该说法成立。") is True


def test_answer_and_conclusion_agree_not_flagged():
    assert contradicts("B（错）", WHY_BAD) is False
    assert contradicts("A（对）", "说法成立，选 A。") is False
    assert contradicts("对", "定义如此，没有例外。") is False


def test_numeric_or_letter_paren_never_flagged():
    # 括号里是数值/字母（普通选择题、计算题）→ 不判，绝不误伤
    assert contradicts("B（-1）", "求导得 -1。") is False
    assert contradicts("42", "两边同乘 42 再移项。") is False
    assert contradicts("B", "应选 B。") is False
    assert contradicts("", "") is False


def test_unreadable_conclusion_polarity_not_flagged():
    # 解析里读不出结论极性 → 不判
    assert contradicts("A（对）", "应选 B") is False
    assert contradicts("A（对）", "") is False


# ---------- parse_phase_b：阶段B 三行协议 ----------

def test_phase_b_fix_parses_ans_separately_from_note():
    v = parse_phase_b(
        "VERDICT: FIX\nANS: B（错）\n"
        "NOTE: 教材：SQA 含计划活动，原说法错误（来源：软件工程教材）。"
    )
    assert v["verdict"] == "FIX"
    assert v["ans"] == "B（错）"
    assert "ANS:" not in v["note"]


def test_phase_b_ok_or_missing_ans():
    assert parse_phase_b("VERDICT: OK\nANS: 无\nNOTE: 与初答一致。")["ans"] == "无"
    assert parse_phase_b("VERDICT: OK\nNOTE: 与初答一致。")["ans"] == ""
    # 模型把 ANS 排到 NOTE 后面：NOTE 的 [\s\S]* 会把它吞掉，ans 仍要拿到、note 里不能留
    v = parse_phase_b("VERDICT: FIX\nNOTE: 原说法错误。\nANS: B（错）")
    assert v["ans"] == "B（错）"
    assert "ANS:" not in v["note"]


# ---------- parse_phase_a：阶段A 五行协议 ----------

def test_phase_a_five_lines_why_before_ans_and_guard_stripped():
    raw = "\n".join([
        "NO: 17",
        "TITLE: SQA活动范围",
        "WHY: 制定软件质量计划属于SQA活动，故说法错误。",
        "ANS: B（错）",
        "CERT: <<check>>",
    ])
    p = parse_phase_a(raw)
    assert p["no"] == "17"
    assert p["ans"] == "B（错）"
    assert "说法错误" in p["why"]
    assert is_self_certain(raw) is False
    assert is_self_certain(raw.replace("<<check>>", "<<ok>>")) is True


def test_phase_a_missing_ans_line_falls_back_to_leftover():
    # 模型没写 ANS 行 → 剥掉字段行，整段当答案；只写 WHY → 正文即答案
    p = parse_phase_a("NO: 3\nTITLE: 概念题\nWHY: 定义如此。\nCERT: <<check>>")
    assert p["ans"]  # 答案栏绝不为空（wait/展示都靠它）
    p2 = parse_phase_a("答案是 B")
    assert p2["ans"] == "答案是 B"
    assert p2["no"] == ""


def test_phase_a_no_placeholder_normalization():
    # 无/none/- → 空串；题号内空白剥掉
    assert parse_phase_a("NO: 无\nANS: 42")["no"] == ""
    assert parse_phase_a("NO: none\nANS: 42")["no"] == ""
    assert parse_phase_a("NO: 1 7\nANS: 42")["no"] == "17"
