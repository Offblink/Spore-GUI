Spore v{VERSION} —— 截图搜题桌面应用（单机版）
================================================

【包里有什么】
  Spore.exe        主程序（截图作答 / 搜题记录 / 设置 / 帮助）
  _internal\       程序依赖目录——Spore.exe 靠它运行，别删
  README.txt       本说明

【注意】
  别把 Spore.exe 单独挪出文件夹——它依赖同目录的 _internal\，单独挪走会报错跑不起来；
  要移动或复制就整个文件夹一起搬。

【数据与隐私】
  所有数据只存在本机，不需要服务器、数据库或账号：
    %LOCALAPPDATA%\Spore\spore.db          搜题记录与科目（唯一数据文件）
    %LOCALAPPDATA%\Spore\ui_settings.json  设置（含大模型 API Key，勿外传）
    %LOCALAPPDATA%\Spore\captures\         截图缓存
    %LOCALAPPDATA%\Spore\logs\             运行日志
  备份：退出程序后复制 spore.db 即可；恢复时覆盖回去。

【启动】
  双击 Spore.exe 直接进主界面（无登录）。
  进「设置」页粘贴大模型 API Key（回车保存）→ 点「测试连接」确认能通。
  之后在任意界面按 Alt+S 框选题目即可搜题；Alt+Z 呼出/收起回答浮窗。
  注意：关窗口只是收进托盘（热键还在），要真正退出请在托盘图标上右键 → 退出。

【排障】
  答完不出结果      → 设置页检查 API Key / 测试连接
  记录不见了        → 确认 spore.db 还在原目录；损坏时可用同目录的 spore.db.bak 回滚
  启动即报数据库错误 → 看 %LOCALAPPDATA%\Spore\logs\client.log
