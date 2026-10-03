Spore v1.0.0 —— 截图搜题桌面应用（Windows 客户端 + 后端一体包）
================================================================

【包里有什么】
  Spore.exe                       客户端（截图作答 / 搜题记录 / 设置 / 帮助）
  spore-backend-1.0.0.jar         后端（Spring Boot，REST + MySQL）
  启动 Spore.bat                  一键启动：先起后端（已起则跳过），再开客户端
  schema.sql                      建库脚本（首次导入用）
  application-local.yml.example   数据库口令模板（复制改名后填写）
  本说明

【前置要件】
  1) JDK 8（推荐；本机若只有其它 Java 8+ 版本，脚本会自动改用 PATH 上的 java）
  2) MySQL（本机 3306）

【首次准备（只做一次）】
  1. 导入表结构（会创建数据库 spore_cms 与 7 张表）：
       mysql -u root -p < schema.sql
  2. 把 application-local.yml.example 复制为 application-local.yml（同目录），
     把 username / password 改成你的 MySQL 账号口令。
     —— 口令只存在你本机这个文件里，请勿外传、勿上传。

【启动】
  双击「启动 Spore.bat」：
    · 后端没在跑 → 以最小化窗口拉起（关掉那个窗口 = 停后端）
    · 然后打开客户端
  客户端首次打开是登录页，输入账号密码（登录成功后本机会记住，之后免登录）；
  进「设置」页粘贴大模型 API Key（回车保存）→ 点「测试连接」确认能通。
  之后在任意界面按 Alt+S 框选题目即可搜题；Alt+Z 呼出/收起回答浮窗。

【排障】
  答完不出结果      → 设置页检查 API Key / 测试连接
  界面一片空白      → 后端没起来：看后端窗口报错，或 logs\spore-gui.log
  题目截图不显示    → 设置页「题库目录」被移动过，重新选一次
  登录失败          → 确认 schema.sql 已导入、application-local.yml 口令正确
