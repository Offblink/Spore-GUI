Spore v{VERSION} —— 截图搜题桌面应用（Windows 客户端 + 后端一体包）
================================================================

【包里有什么】
  Spore.exe                       客户端（截图作答 / 搜题记录 / 设置 / 帮助）
                                  双击它即可：后端随客户端自动启动，不弹命令行窗口
  _internal\                      程序依赖目录——Spore.exe 靠它运行，别删
  spore-backend-{VERSION}.jar         后端（Spring Boot，REST + MySQL）——请与 Spore.exe 同目录
  schema.sql                      建库脚本（首次导入用）
  application-local.yml.example   数据库口令模板（复制改名后填写）
  本说明

【注意】
  别把 Spore.exe 单独挪出文件夹——它依赖同目录的 _internal\，单独挪走会报错跑不起来；
  要移动或复制就整个文件夹一起搬。

【前置要件】
  1) JDK 8（推荐；本机若只有其它 Java 8+ 版本，会自动改用 PATH 上的 java）
  2) MySQL（本机 3306）

【首次准备（只做一次）】
  1. 导入表结构（会创建数据库 spore_cms 与 7 张表）：
       mysql -u root -p < schema.sql
     —— 注意：schema.sql 是「先删表再建表」，重跑会清空该库所有数据。
        只在全新装机时跑一次；以后升级版本不要重跑它。
  2) 数据库口令二选一（v1.3.3 起推荐第一种，不用手动改任何文件）：
       · 界面填：直接双击 Spore.exe。若连不上数据库会自动弹出「数据库配置」页，
         填账号/密码 → 点「保存并重启后端」即可，Spore 自己写配置。
         （地址/端口/库名已按默认值 localhost:3306/spore_cms 预填，收在「高级设置」里，
           只有改过端口或库名的装机才需要点开。）
       · 手动配：把 application-local.yml.example 复制为 application-local.yml（同目录），
         把 username / password 改成你的 MySQL 账号口令，再双击 Spore.exe。
     —— 口令只存在你本机这个文件里，请勿外传、勿上传、不进 git、不随包分发。

【启动】
  双击 Spore.exe：
    · 后端没在跑 → 客户端自己把它拉起来（不弹命令行窗口，首次约 6 秒，有进度提示）
    · 后端已在跑 → 直接复用，不重复起、也不接管
    · 关掉客户端 = 关掉它自己拉起的那个后端（你自己起的后端它不动）
  客户端首次打开是登录页，输入账号密码（登录成功后本机会记住，之后免登录）；
  进「设置」页粘贴大模型 API Key（回车保存）→ 点「测试连接」确认能通。
  之后在任意界面按 Alt+S 框选题目即可搜题；Alt+Z 呼出/收起回答浮窗。
  注意：关窗口只是收进托盘（热键还在），要真正退出请在托盘图标上右键 → 退出。

【排障】
  答完不出结果      → 设置页检查 API Key / 测试连接
  启动时弹「数据库配置」页
                    → 连不上 MySQL：在页里改对账号/密码并点「保存并重启后端」；
                      或确认 MySQL 服务已启动、schema.sql 已导入
                      （地址/端口/库名不对时，点开「高级设置」再改）
  启动时弹「后端启动失败」
                    → 看弹窗里的后端控制台尾部；全文在
                      %LOCALAPPDATA%\Spore\logs\backend-console.log
                      （装进 Program Files 这类不可写的目录必然落这儿；
                        目录自己可写时才用 exe 旁的 logs\）
                      常见原因：缺 JDK、Spore.exe 不在 jar 同目录
  界面一片空白      → 后端没起来：看上面那个 logs\ 目录里的
                      spore-gui.log / backend-console.log
  题目截图不显示    → 设置页「题库目录」被移动过，重新选一次
  登录失败          → 确认 schema.sql 已导入、application-local.yml 口令正确
