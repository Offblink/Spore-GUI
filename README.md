# Spore

截图搜题桌面应用：框选题目 → 大模型读题作答 → 自动联网核实 → 全程留档，可继续追问。

## 组成

| 部分 | 技术 | 说明 |
| --- | --- | --- |
| 后端 `src/` | Spring Boot + MyBatis-Plus + MySQL | 本机 8080 提供 REST 接口、题图存储、账号与同步 |
| 客户端 `client/` | Python 3.13 + PySide6（Fluent Widgets） | 截图作答、搜题记录、设置、帮助 |

## 快速开始

1. 准备环境：JDK 8、Maven、Python 3.13（本机已装好即可）。
2. 双击仓库根目录的 `start-spore.bat`：自动拉起后端（已在跑则跳过）与客户端。
3. 首次使用：打开客户端「设置」页，粘贴大模型 API Key（回车保存），点「测试连接」确认能通。

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
├─ start-spore.bat       一键启动（后端 + 客户端）
└─ pom.xml
```

## 许可

课程设计项目，仅供学习使用。
