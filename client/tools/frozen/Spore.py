"""冻结入口：把包内 main 拉起来。

PyInstaller 把入口脚本当 `__main__` 跑——`spore_client/main.py` 里全是相对
import，直接当入口会 `attempted relative import with no known parent package`；
这一层薄壳先 import 包、再调 main()。
"""

from spore_client.main import main

if __name__ == "__main__":
    raise SystemExit(main())
