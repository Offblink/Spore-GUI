"""帮助页（2026-10-03 用户要求）：上手三步、快捷键、页面速览、配对与常见问题。

文案纪律：面向读者、通俗简洁，不写开发内幕；卡片样式复用设置页，
两页观感一致（build_card / kbd_badge / setting_label 同源）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .settings import build_card, hint_label, kbd_badge, setting_label


class HelpPane(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("helpPage")   # FluentWindow.addSubInterface 要求非空

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }")
        body = QWidget()
        body.setStyleSheet("QWidget { background: transparent; }")
        stack = QVBoxLayout(body)
        stack.setContentsMargins(0, 0, 6, 0)
        stack.setSpacing(16)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # ================= 卡一：快速上手 =================
        card, lay, _ = build_card("快速上手", "三步开始用")
        for line in (
            "1. 打开「设置」页，粘贴大模型 API Key（回车保存），"
            "点「测试连接」确认能通。",
            "2. 任意界面按 Alt+S，框选题目区域。",
            "3. 几秒后看回答；想继续追问，就在底部输入框接着说。",
        ):
            lay.addWidget(setting_label(line))
        lay.addWidget(hint_label("API Key 只需配一次，之后随时开用。"))
        stack.addWidget(card)

        # ================= 卡二：快捷键 =================
        card, lay, _ = build_card("快捷键")
        for cap, key in (("截图作答：", "Alt+S"), ("呼出/收起回答浮窗：", "Alt+Z")):
            row = QHBoxLayout()
            row.addWidget(setting_label(cap))
            row.addWidget(kbd_badge(key))
            row.addStretch(1)
            lay.addLayout(row)
        lay.addWidget(hint_label(
            "全局热键随程序常驻；关窗只是收进托盘，"
            "双击托盘图标打开，托盘右键「退出」才真正退出。"))
        stack.addWidget(card)

        # ================= 卡三：页面速览 =================
        card, lay, _ = build_card("页面速览")
        for line in (
            "搜题记录：左栏是科目与会话，点一条会话看内容；"
            "底部「接着问」就地继续对话，🔍「核实一下」补做联网核实；"
            "行尾 ★ 收藏、✎ 改名、⇄ 移入科目、× 删除（连带删除题图）。",
            "日志：程序运行日志，遇到问题可以来这里看。",
            "设置：模型、核实方式、检索与题库目录都在这里。",
        ):
            lay.addWidget(setting_label(line))
        stack.addWidget(card)

        # ================= 卡四：手机扫码配对 =================
        card, lay, _ = build_card("手机扫码配对")
        lay.addWidget(setting_label(
            "点主界面左下角的头像，弹出二维码；手机扫一下即可接入"
            "（二维码 10 分钟内有效）。"))
        stack.addWidget(card)

        # ================= 卡五：数据都在哪 =================
        card, lay, _ = build_card("数据都在哪")
        for line in (
            "设置与日志：本机 LOCALAPPDATA/Spore 目录"
            "（ui_settings.json 里存着 API Key，请不要外传）。",
            "截图缓存：同目录的 captures；题图：设置页里的「题库目录」"
            "（默认 data/attachments）。",
        ):
            lay.addWidget(setting_label(line))
        stack.addWidget(card)

        # ================= 卡六：常见问题 =================
        card, lay, _ = build_card("常见问题")
        for line in (
            "回答不出来？先到设置页看 API Key 是否「已设置」，再点「测试连接」。",
            "界面一直空白？确认后端已启动——双击 start-spore.bat 会自动拉起。",
            "截图不显示？题库目录被移动过就重新选一次（设置页「切换…」）。",
            "检索没结果？网络受限时在设置页填本机代理，"
            "走 DDG→BING→BRAVE 检索链。",
        ):
            lay.addWidget(setting_label(line))
        stack.addWidget(card)

        stack.addStretch(1)
