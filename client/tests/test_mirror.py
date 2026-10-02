"""mirror.write_turn：真写临时目录，markdown 内容/文件名安全/best-effort 不抛。"""

import datetime

from spore_client.mirror import write_turn


def _messages() -> list[dict]:
    return [
        {"role": "user", "kind": "chat", "text": "这道题怎么做", "hasImage": True},
        {"role": "assistant", "kind": "answer", "no": "1",
         "title": "一元二次方程", "ans": "x=1 或 x=-2", "why": "判别式法",
         "think": "SECRET-THINK",
         "tools": ["检索 一元二次方程"],
         "verifyVerdict": "OK", "verifyNote": "与教材一致",
         "verifyThink": "SECRET-VERIFY"},
        {"role": "user", "kind": "chat", "text": "再讲讲判别式"},
    ]


def test_writes_markdown_without_think(tmp_path):
    md = write_turn(root=str(tmp_path), sub_root="Spore/sessions",
                    title="作业第3题", messages=_messages(),
                    image_path=None, with_image=False)
    assert md is not None and md.exists()
    assert md.parent.name == datetime.date.today().isoformat()
    assert md.parent.parent == tmp_path / "Spore" / "sessions"
    text = md.read_text(encoding="utf-8")
    assert text.startswith("# 作业第3题")
    assert "x=1 或 x=-2" in text              # 初答正文在
    assert "这道题怎么做" in text              # 提问在
    assert "再讲讲判别式" in text              # 追问在
    assert "检索 一元二次方程" in text          # 工具小票在
    assert "通过" in text                      # 核实 verdict+note 在
    assert "SECRET" not in text                # think / verifyThink 绝不落盘


def test_filename_sanitized(tmp_path):
    md = write_turn(root=str(tmp_path), sub_root="Spore/sessions",
                    title='第3题: a/b\\c*d?e"f<g>h|i\nx',
                    messages=_messages(), image_path=None, with_image=False)
    assert md is not None
    assert not any(ch in md.name for ch in '\\/:*?"<>|\n')
    assert md.name.endswith(".md")


def test_filename_length_capped(tmp_path):
    md = write_turn(root=str(tmp_path), sub_root="", title="长" * 300,
                    messages=_messages(), image_path=None, with_image=False)
    assert md is not None
    assert len(md.stem) <= 80


def test_image_copied_only_when_with_image(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\xff\xd8fakejpg")
    md = write_turn(root=str(tmp_path), sub_root="Spore/sessions",
                    title="带图题", messages=_messages(),
                    image_path=str(img), with_image=False)
    assert md is not None and not md.with_suffix(".jpg").exists()
    md2 = write_turn(root=str(tmp_path), sub_root="Spore/sessions",
                     title="带图题", messages=_messages(),
                     image_path=str(img), with_image=True)
    assert md2 is not None and md2.with_suffix(".jpg").exists()


def test_failure_returns_none_not_raise(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")   # root 是文件 → 写不进去
    md = write_turn(root=str(blocker), sub_root="Spore/sessions",
                    title="注定失败", messages=_messages(),
                    image_path=None, with_image=False)
    assert md is None                        # best-effort：收敛不抛


def test_empty_title_gets_fallback(tmp_path):
    md = write_turn(root=str(tmp_path), sub_root="", title="  ..  ",
                    messages=[], image_path=None, with_image=False)
    assert md is not None
    assert md.stem == "未命名会话"        # 全是点/空格 → 安全名回落
