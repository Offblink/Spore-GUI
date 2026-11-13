# Spore

截图搜题桌面应用（Windows）。按 `Alt+S` 框选题目，大模型分两阶段作答（初答 → 联网核实），
回答与历史会话都留在本机。

**v1.5.0 起是单机应用**：没有后端服务、没有账号、没有手机同步，也不依赖 MySQL / JDK / Tomcat。
所有数据在一个 SQLite 文件里，启动即用。

## 下载与安装

Release 里的 `Spore-<版本>-win64.zip` 解压后用里面的 `Spore.exe` 启动（解压出来是一个文件夹）：

```
Spore-<版本>-win64\
├─ Spore.exe
├─ _internal\      ← 依赖目录，别删
└─ README.txt
```

> **别把 `Spore.exe` 单独挪出文件夹**：它依赖同目录的 `_internal\`。

首次打开进「设置」页粘贴大模型 API Key（回车保存），点「测试连接」确认能通即可。
之后关窗口只是收进托盘，托盘右键「退出」才真正退出。

## 数据与隐私

全部只在本机，不上传、不联网同步：

| 路径（`%LOCALAPPDATA%\Spore\`） | 内容 |
| --- | --- |
| `spore.db` | 搜题记录与科目（唯一数据文件） |
| `ui_settings.json` | 模型 / 检索设置，**含 API Key，勿外传** |
| `captures\` | 截图缓存 |
| `logs\client.log` | 运行日志 |

备份与恢复：退出程序后复制 `spore.db`；升级版本前程序会留一份 `spore.db.bak`。

## 功能

- **截图作答**：Alt+S 框选题目，两阶段作答（初答 → 联网核实），检索过程以小票展示
- **回答与记录吃完整 markdown**：标题、表格（带网格线、宽表自动撑满气泡）、列表、引用、
  代码块、公式渲成图（离线 mathtext，渲染失败退回源码不丢内容）
- **搜题记录**：按科目归类、收藏、重命名、移入科目、删除（连带删除题图）；标题即时检索；
  「批量选择」进多选（单选框涂抹连选、底栏**全选/取消全选**只作用于当前筛选），批量收藏·移入·删除
- **深色 / 浅色主题**：设置页「外观」切「跟随系统 / 浅色 / 深色」，点一下全应用立即换
  （含回答浮窗）；浅色是孢子粉 `#EC4899`、深色是 Fungi 青 `#2DD4BF`，与手机端同一套配色
- **继续追问**：在记录页或回答浮窗里接着聊，回答落回同一会话
- **手动核实**：关掉自动核实后，点「核实一下」再联网核实

## 快捷键

| 按键 | 作用 |
| --- | --- |
| `Alt+S` | 截图并可框选，发起一题 |
| `Alt+Z` | 呼出 / 收起回答浮窗 |

## 架构

单进程 PySide6 应用；界面直接读写本机 SQLite（`spore_client/store.py`，WAL），
不监听任何端口，也没有后台服务：

```
Spore.exe
├─ spore_client/       UI（记录页 / 设置 / 帮助 / 回答浮窗）+ 作答链路
├─ spore_client/store.py   SQLite 数据层（文章、科目）
└─ %LOCALAPPDATA%\Spore\spore.db
```

## 从源码运行

```bash
cd client
.venv/Scripts/python.exe -m spore_client.main
```

依赖：Python 3.13、PySide6 6.10.2、PySide6-Fluent-Widgets 1.11.3、httpx、markdown、Pillow、keyboard。
源码运行同样把数据写进 `%LOCALAPPDATA%\Spore\`（可用 `SPORE_HOME` 重定向）。

### 门禁

```bash
cd client
ruff check .
.venv/Scripts/python.exe -m pytest
```

### 构建 exe

```bash
# 干净构建 venv（别用开发 venv：它会带进全局 PyQt5 / torch）
python -m venv --without-pip client/.venv-build
python -m pip --python client/.venv-build/Scripts/python.exe install \
  "PySide6==6.10.2" "PySide6-Fluent-Widgets==1.11.3" \
  pyinstaller httpx markdown Pillow keyboard

python client/tools/build_exe.py               # 产物 client/dist/Spore/
python client/tools/make_release_bundle.py    # 发行 zip
python client/tools/factory_check.py          # 出厂检查（必须用 .venv-build）
```

## 从 1.4.x 升级

1.4.x 的数据在 MySQL（`spore_cms`）里。一次性迁移（只读源库、逐行校验）：

```bash
cd client
.venv/Scripts/python.exe tools/migrate_mysql_to_sqlite.py --force
```

迁移后旧库保持原样，可直接回滚旧版本。1.4.x 的账号、角色、同步状态与操作日志不会迁移
（这些功能已下线）；题图只有仍在本机截图缓存里的那些还能显示。

## 目录结构

```
spore-gui/
├─ client/
│  ├─ spore_client/       客户端（store.py 数据层、records / settings / answer 等）
│  ├─ tests/              pytest
│  └─ tools/              构建、发版、迁移脚本
├─ docs/
└─ README.md
```

## 许可

MIT
