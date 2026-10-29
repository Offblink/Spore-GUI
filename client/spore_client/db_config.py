"""首启数据库配置页：后端因数据库连不上而起不来时，让用户在界面填连接信息，
客户端写 application-local.yml 并重启后端——用户全程不手动碰配置文件。

为什么这页不在「登录页」、而在后端启动失败这条路径上：数据库口令是后端能启动的
前置条件。口令错时 Spring 上下文初始化失败、JVM 直接退出、端口从没绑定，登录页
根本不存在（2026-10-29 实测：Access denied → HikariPool 初始化失败 → context
取消 refresh → JVM 退出，端口从没 LISTENING）。所以配置页必须挂在「后端起不来」
这条失败路径上，而不是嵌进登录页。

v1.3.4 起后端自动建库（DatabaseBootstrapConfig）：库/表/角色/权限缺什么补什么、
全程幂等绝不 DROP。所以用户不必先在 MySQL 里建库——但这一步仍需一个「有建库权限」
的账号，口令错 / 缺建库权限 / MySQL 没起都会让后端起不来，仍落到本页让用户改。

评分红线不破：口令只写进本机 application-local.yml（gitignore 敏感件），
绝不进 git、不进 release zip。

界面默认只露「账号 / 密码」两项：地址/端口/库名是常量（application.yml 写死
localhost:3306/spore_cms），让所有用户复述程序已经知道的值是亏的——一旦打错
端口/库名只会得到看不懂的连接失败。三者收进「高级设置」折叠区，只服务极少数
改过端口/库名的装机。
"""

from __future__ import annotations

import os
import re
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)

from .backend import EmbeddedBackend, launch_dir
from .log import get_logger

LOG = get_logger()

# 数据库连不上/建不了时 Spring 控制台的特征串——用它们把「数据库问题」
# 从「后端起不来的其他原因」（缺 jar、缺 java、端口被占、卡半路）里分出来。
# 自动建库（v1.3.4 起）后，「库不存在」不再致命（应用自己建），但账号缺建库权限、
# 口令错、MySQL 没起仍会让后端起不来——这些都要落到配置页让用户改账号/口令。
DB_FAILURE_MARKERS = (
    "Exception during pool initialization",
    "Access denied for user",           # 口令错，或账号无该库权限
    "CREATE command denied",            # 账号能连但无建库权限 → 换有权限的账号
    "CannotGetJdbcConnectionException",
    "Failed to obtain JDBC Connection",
    "CommunicationsException",
    "Communications link failure",      # MySQL 服务没起
    "自动建库失败",                       # DatabaseBootstrapConfig 抛的中文原因
    "自动初始化表结构失败",
)

# application.yml 同款连接串后缀（时区/编码对齐，改库名/地址不影响这些）
URL_SUFFIX = ("?useUnicode=true&characterEncoding=utf8"
              "&serverTimezone=Asia/Shanghai")
DEFAULTS = {"host": "localhost", "port": "3306",
            "database": "spore_cms", "username": "root"}


def looks_like_db_failure(console_text: str) -> bool:
    """后端控制台文本里是否出现数据库连接失败的特征串。"""
    return any(marker in console_text for marker in DB_FAILURE_MARKERS)


def _yaml_str(value: str) -> str:
    """YAML 双引号标量：只转义 \\ 和 \"（其余字符在双引号内都安全）。"""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_local_yml(url: str, username: str, password: str) -> str:
    """生成 application-local.yml 全文（结构与 .example 一致，口令留在本机）。"""
    return (
        "# 由 Spore 客户端「数据库配置」页自动生成。"
        "口令只留在本机，不要提交到 git、不要随包分发。\n"
        "spring:\n"
        "  datasource:\n"
        f"    url: {_yaml_str(url)}\n"
        f"    username: {_yaml_str(username)}\n"
        f"    password: {_yaml_str(password)}\n"
    )


def write_local_yml(path: Path, url: str, username: str, password: str) -> None:
    """原子写 application-local.yml：先写临时文件再 replace，别留半截配置。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yml.tmp")
    tmp.write_text(render_local_yml(url, username, password), encoding="utf-8")
    os.replace(tmp, path)


def parse_local_yml(text: str) -> dict[str, str]:
    """从现有 application-local.yml 里捞 host/port/database/username 预填界面。

    只认这个文件的固定结构（url/username 两个键），取不到就回落默认值。
    """
    out = dict(DEFAULTS)
    m = re.search(r'^\s*url:\s*["\']?jdbc:mysql://([^:/]+):(\d+)/(\w+)',
                  text, re.M)
    if m:
        out["host"], out["port"], out["database"] = (m.group(1), m.group(2),
                                                     m.group(3))
    m = re.search(r'^\s*username:\s*["\']?(.*?)["\']?\s*$', text, re.M)
    if m and m.group(1):
        out["username"] = m.group(1)
    return out


def config_path_for(backend: EmbeddedBackend) -> Path | None:
    """application-local.yml 该写到哪——必须与后端**读**的位置一致，否则写了不生效。

    与 :func:`config_args` 的搜索顺序逐字对齐（写哪儿 = 读哪儿）：
    1. 开发态 ``<launch>/src/main/resources/``（gitignore 敏感件、Spring 原生加载点，优先）
    2. 发行态 ``<launch>/``（jar 同目录）

    注意取 ``launch``（jar 所在目录）而非 ``runtime_base``：1.3.2 起 ``config_args``
    用**绝对路径**指向 launch（修 Program Files 下 cwd 被 ``runtime_base`` 迁走、
    Spring 按 file:./ 读不到 jar 旁口令文件的 bug），已与 cwd 解耦——配置页若还写
    ``runtime_base`` 就写错地方了。两处都没 yml 时落 launch（写完重启后
    ``config_args`` 就能发现它）。
    """
    if backend.jar is None:
        return None
    launch = launch_dir(backend.jar)
    for cfg_dir in (launch / "src" / "main" / "resources", launch):
        if (cfg_dir / "application-local.yml").is_file():
            return cfg_dir / "application-local.yml"
    return launch / "application-local.yml"


class _RestartTask(QThread):
    """写完 yml 后重启后端（Spring 冷启动几秒），别卡 UI。"""

    ok = Signal()
    failed = Signal(str)

    def __init__(self, backend: EmbeddedBackend, parent=None):
        super().__init__(parent)
        self.backend = backend

    def run(self):
        try:
            if not self.backend.start_if_needed():
                self.ok.emit()   # 已在监听（用户手起了一个）也算就绪
                return
            if self.backend.wait_ready(timeout=60):
                self.ok.emit()
                return
            console = self.backend.console_text()
            if looks_like_db_failure(console):
                # 别把 Java 堆栈糊给用户（89 帧会把窗口撑爆）：说人话，堆栈进日志。
                LOG.error("backend still failing after db config:\n%s", console)
                self.failed.emit("数据库仍然连不上——口令或地址/端口/库名可能不对，"
                                 "请检查后重试（详见 logs\\backend-console.log）")
            else:
                self.failed.emit(self.backend.tail_console()
                                 or "后端没有按时监听 8080")
        except Exception as e:   # noqa: BLE001 — 后台线程任何异常都要回到界面
            LOG.error("backend restart failed: %s", e)
            self.failed.emit(str(e))


class DbConfigWindow(QWidget):
    """数据库连接配置页。配置成功发 configured、跳过发 skipped，由 app 转登录页。"""

    configured = Signal()
    skipped = Signal()

    def __init__(self, backend: EmbeddedBackend, parent=None,
                 note: str | None = None):
        super().__init__(parent)
        self.backend = backend
        self._task: _RestartTask | None = None

        self.setWindowTitle("Spore")
        self.resize(460, 310)   # 收起态（只露账号+密码）；展开高级区会自动撑高

        cur: dict[str, str] = {}
        cfg_path = config_path_for(backend)
        if cfg_path is not None and cfg_path.is_file():
            with suppress(OSError):
                cur = parse_local_yml(cfg_path.read_text(encoding="utf-8"))

        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(14)

        title = StrongBodyLabel("数据库配置")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        root.addWidget(title)
        root.addSpacing(4)

        hint = CaptionLabel(
            "后端连不上数据库，所以起不来。填好账号密码，Spore 会自动建库、建表、"
            "配好角色并重启后端——不用手动改任何文件，也不用先在 MySQL 里建库。")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.username = LineEdit()
        self.username.setText(cur.get("username", DEFAULTS["username"]))
        self.password = LineEdit()
        self.password.setPlaceholderText("数据库密码")
        self.password.setEchoMode(QLineEdit.Password)

        root.addWidget(self._row("账号", self.username))
        root.addWidget(self._row("密码", self.password))

        # 地址/端口/库名默认常量（localhost:3306/spore_cms），只服务改过端口/库名的装机
        self.adv_toggle = PushButton("高级设置（地址 / 端口 / 库名）")
        self.adv_toggle.setCheckable(True)
        root.addWidget(self.adv_toggle)

        self.adv_box = QWidget()
        adv_lay = QVBoxLayout(self.adv_box)
        adv_lay.setContentsMargins(0, 0, 0, 0)
        adv_lay.setSpacing(14)
        self.host = LineEdit()
        self.host.setText(cur.get("host", DEFAULTS["host"]))
        self.port = LineEdit()
        self.port.setText(cur.get("port", DEFAULTS["port"]))
        self.database = LineEdit()
        self.database.setText(cur.get("database", DEFAULTS["database"]))
        adv_lay.addWidget(self._row("地址", self.host))
        adv_lay.addWidget(self._row("端口", self.port))
        adv_lay.addWidget(self._row("库名", self.database))
        self.adv_box.hide()          # 默认收起：正常用户只看到账号+密码
        root.addWidget(self.adv_box)

        self.status = CaptionLabel("")
        self.status.setTextColor("#d13438", "#d13438")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        if note:
            self.status.setText(note)

        btn_row = QHBoxLayout()
        self.save_btn = PrimaryPushButton("保存并重启后端")
        self.skip_btn = PushButton("返回登录页")
        btn_row.addStretch(1)
        btn_row.addWidget(self.skip_btn)
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)
        root.addStretch(1)

        self.save_btn.clicked.connect(self._save)
        self.skip_btn.clicked.connect(self.skipped.emit)
        self.password.returnPressed.connect(self._save)
        # 折叠开关：默认收起，点开才露地址/端口/库名（正常用户不需要它们）
        self.adv_toggle.toggled.connect(self._toggle_advanced)

    # ---------- 布局小工具 ----------
    @staticmethod
    def _row(label: str, edit: LineEdit) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lb = BodyLabel(label)
        lb.setFixedWidth(44)
        lay.addWidget(lb)
        lay.addWidget(edit, 1)
        return w

    # ---------- 行为 ----------
    def _toggle_advanced(self, checked: bool):
        """展开/收起地址·端口·库名。默认收起——这三项是常量，正常用户不该碰。"""
        self.adv_box.setVisible(checked)
        self.adv_toggle.setText("高级设置" if checked else "高级设置（地址 / 端口 / 库名）")

    def _validate(self) -> bool:
        if not self.host.text().strip():
            self.status.setText("数据库地址必填")
            return False
        port = self.port.text().strip()
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            self.status.setText("端口要是 1-65535 的数字")
            return False
        if not self.database.text().strip():
            self.status.setText("数据库名必填")
            return False
        if not self.username.text().strip():
            self.status.setText("账号必填")
            return False
        return True

    def _save(self):
        if not self._validate():
            return
        if self._task is not None and self._task.isRunning():
            return   # 上一发还没回来，别叠加
        cfg_path = config_path_for(self.backend)
        if cfg_path is None:
            self.status.setText("找不到后端 jar，无法定位配置文件")
            return
        url = (f"jdbc:mysql://{self.host.text().strip()}:"
               f"{self.port.text().strip()}/"
               f"{self.database.text().strip()}{URL_SUFFIX}")
        try:
            write_local_yml(cfg_path, url, self.username.text().strip(),
                            self.password.text())
        except OSError as e:
            self.status.setText(f"写配置文件失败：{e}")
            return
        LOG.info("db config written to %s", cfg_path)
        self.save_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.status.setText("正在重启后端…")
        self._task = _RestartTask(self.backend, self)
        self._task.ok.connect(self._on_ok)
        self._task.failed.connect(self._on_fail)
        self._task.finished.connect(self._reset_buttons)
        self._task.start()

    def _on_ok(self):
        LOG.info("backend up after db config → login page")
        self.configured.emit()

    def _on_fail(self, msg: str):
        self.status.setText(msg)

    def _reset_buttons(self):
        self.save_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
