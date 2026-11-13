"""运行依赖可导入：CI 只按 `client/requirements.txt` 装包，所以这条是「清单漏项」的
唯一探针。

2026-11-13 事故：v1.5.0 把 matplotlib 从安装清单删了，本地开发 venv 是
`--system-site-packages`（看得见全局 matplotlib），公式用例全绿；CI 干净装包 →
11 条 LaTeX 用例红，且打包出的 exe 里公式静默退化成源码。
"""

import importlib

import pytest

RUNTIME_MODULES = ("httpx", "markdown", "PIL", "keyboard", "matplotlib")


@pytest.mark.parametrize("mod", RUNTIME_MODULES)
def test_runtime_dependency_imports(mod):
    importlib.import_module(mod)
