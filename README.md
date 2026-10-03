# Spore

截图搜题桌面应用：框选题目 → 大模型读题作答 → 自动联网核实 → 全程留档，可继续追问。

## 组成

| 部分 | 技术 | 说明 |
| --- | --- | --- |
| 后端 `src/` | Spring Boot + MyBatis-Plus + MySQL | 本机 8080 提供 REST 接口、题图存储、账号与同步 |
| 客户端 `client/` | Python 3.13 + PySide6（Fluent Widgets） | 截图作答、搜题记录、设置、帮助 |

## 下载

到 [Releases](https://github.com/Offblink/Spore-GUI/releases) 下载 **`Spore-<版本>-win64.zip`（一体化，推荐）**：
内含客户端 `Spore.exe`、后端 jar、`schema.sql`（建库脚本）与数据库口令模板。
首次准备（只做一次）：

1. 安装 **JDK 8** 与 **MySQL**，导入表结构：`mysql -u root -p < schema.sql`
2. 复制 `application-local.yml.example` 为 `application-local.yml`，填入你的 MySQL 账号口令
3. 双击 `Spore.exe` —— 后端由客户端自己拉起（**不弹命令行窗口**），关客户端即停后端

> `Spore.exe` 必须与 `spore-backend-*.jar` 同目录：客户端按 exe 所在目录找后端。
> 单个 `Spore-<版本>-win64.exe` 也挂在 Releases 上，但它**只是客户端**，需要你自备后端。
> 用源码跑整套（含后端开发）见下方「快速开始」。

## 快速开始

1. 准备环境：JDK 8、Maven、Python 3.13（本机已装好即可）。
2. 构建后端 jar：`mvn clean package -DskipTests`（客户端要从 `target/` 拿 jar 起后端）。
3. 双击仓库根目录的 `start-spore.bat` 拉起客户端——**后端由客户端自己起，不弹命令行窗口**，
   退出客户端即停后端；你先自己跑了 `mvn spring-boot:run` 的话，它检测到 8080 在监听就直接复用。
4. 首次使用：打开客户端「设置」页，粘贴大模型 API Key（回车保存），点「测试连接」确认能通。

### 从源码构建客户端 exe

```bash
# 1) 干净构建 venv（别用开发 venv：它会带进全局 PyQt5 / torch）
python -m venv --without-pip client/.venv-build
python -m pip --python client/.venv-build/Scripts/python.exe install \
  "PySide6==6.10.2" "PySide6-Fluent-Widgets==1.11.3" \
  pyinstaller httpx markdown qrcode Pillow keyboard
# 2) 构建 + 自检（图标、产物、窗口存活、sha256）
python client/tools/build_exe.py
```

产物 `client/dist/Spore-<版本>-win64.exe`；打包配方在 `client/Spore.spec`。

## 功能

- **截图作答**：Alt+S 框选题目，两阶段作答（初答 → 联网核实），检索过程以小票展示
- **搜题记录**：按科目归类、收藏、重命名、移入科目、删除（连带删除题图）；标题即时检索
- **继续追问**：在记录页或回答浮窗里接着聊，回答落回同一会话
- **手动核实**：关掉自动核实后，点「核实一下」再联网核实
- **手机扫码配对**：点主界面左下角头像出二维码，手机扫码接入
- **题库目录可切换**：题图随目录整体迁移（设置页）

## 快捷键

| 按键 | 作用 |
| --- | --- |
| `Alt+S` | 截图并可框选，发起一题 |
| `Alt+Z` | 呼出 / 收起回答浮窗 |

## 配置与数据

- 设置与日志：`%LOCALAPPDATA%\Spore\`
  - `ui_settings.json`：模型、核实、检索等设置，**内含 API Key，请勿外传**
  - `logs\`：运行日志；`captures\`：截图缓存
- 题图：后端「题库目录」（默认 `data/attachments`，设置页可切换）
- 数据库口令：写在 `src/main/resources/application-local.yml`（不进 git）

## 目录结构

```
spore-gui/
├─ src/main/java/…       后端（REST / 存储 / 同步 / 账号）
├─ client/spore_client/  客户端（answer 引擎、records 记录页、settings 设置、help_page 帮助）
├─ client/tests/         客户端测试
├─ start-spore.bat       一键启动客户端（后端随客户端自动起停）
└─ pom.xml
```

## 许可

课程设计项目，仅供学习使用。
