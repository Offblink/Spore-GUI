"""冻结入口：把包内 main 拉起来；另带一条 `--selftest` 通道给 build_exe 用。

PyInstaller 把入口脚本当 `__main__` 跑——`spore_client/main.py` 里全是相对
import，直接当入口会 `attempted relative import with no known parent package`；
这一层薄壳先 import 包、再调 main()。

`--selftest <out.json>`：在**冻结环境里**跑一遍懒加载链路（matplotlib → pyparsing →
公式出图），结果写文件、返回码即判据。窗口版 exe 没有 stdout，且 build_exe 的自检
只看「窗口出现」抓不到这类静默降级（2026-11-13：spec 排掉 unittest 导致 matplotlib
import 崩，公式全部退化成源码，窗口照常出现）。
"""

import json
import sys
from pathlib import Path


def selftest(out_path: str) -> int:
    ok, detail = False, ""
    try:
        from spore_client.latex_render import extract_math

        _, blocks = extract_math("$a^2+b^2=c^2$")
        ok = bool(blocks) and "data:image/png" in blocks[0]
        detail = f"blocks={len(blocks)}"
    except Exception:                  # noqa: BLE001 — 失败原因必须原样带回
        import traceback

        detail = traceback.format_exc(limit=8)
    Path(out_path).write_text(
        json.dumps({"ok": ok, "detail": detail}, ensure_ascii=False),
        encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        raise SystemExit(selftest(sys.argv[2]))
    from spore_client.main import main

    raise SystemExit(main())
