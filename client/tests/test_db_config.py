"""db_config 契约：DB 失败识别 / db.properties 生成+原子写 / 旧配置预填 / 写入位置。

这些是纯逻辑，不碰 Qt——配置页 UI 只是把它们串起来。
"""

from spore_client.db_config import (  # noqa: F401 — qapp 触发 Qt offscreen 初始化
    DEFAULTS,
    URL_SUFFIX,
    config_path_for,
    looks_like_db_failure,
    parse_db_properties,
    render_db_properties,
    write_db_properties,
)

# 真实 HikariCP 秒退日志里抓的片段（2026-10-29 实测）
_DB_DENIED = ("HikariPool-1 - Exception during pool initialization.\n"
              "java.sql.SQLException: Access denied for user 'root'@'localhost'")
_DB_UNREACHABLE = ("### Cause: org.springframework.jdbc."
                   "CannotGetJdbcConnectionException: Failed to obtain JDBC "
                   "Connection")
_NOT_DB_MISSING_WAR = "没找到后端 war（spore-backend-*.war / target/spore-gui.war）"
_NOT_DB_MISSING_TOMCAT = "没找到 Tomcat 9：发行包要有 tomcat\\ 目录"
_NOT_DB_MISSING_JAVA = "没找到 Java：请安装 JDK 8"
# 自动建库（v1.3.4）后的新失败形态：账号能连但无建库权限
_DB_NO_CREATE_PRIV = ("java.sql.SQLException: CREATE command denied to user "
                      "'spore'@'localhost' for database 'spore_cms'")
# DatabaseBootstrapConfig 自己抛的中文原因（自动建库/初始化表结构失败）
_DB_AUTO_CREATE_FAIL = "自动建库失败：无法用当前账号在 jdbc:mysql://localhost:3306/ 上执行建库"
_DB_AUTO_INIT_FAIL = "自动初始化表结构失败：已连上 jdbc:mysql://... 但执行 schema-init.sql 出错"


# ---------- DB 失败识别 ----------

def test_db_denied_is_db_failure():
    assert looks_like_db_failure(_DB_DENIED)


def test_db_unreachable_is_db_failure():
    assert looks_like_db_failure(_DB_UNREACHABLE)


def test_missing_war_is_not_db_failure():
    """缺 war 也「后端起不来」，但绝不能弹数据库配置页——判据要精准。"""
    assert not looks_like_db_failure(_NOT_DB_MISSING_WAR)


def test_missing_tomcat_is_not_db_failure():
    """缺 Tomcat 同理：不是数据库问题，弹配置页没意义（填了也起不来）。"""
    assert not looks_like_db_failure(_NOT_DB_MISSING_TOMCAT)


def test_missing_java_is_not_db_failure():
    assert not looks_like_db_failure(_NOT_DB_MISSING_JAVA)


def test_no_create_privilege_is_db_failure():
    """账号能连但无建库权限（v1.3.4 自动建库后的新形态）→ 要弹配置页换账号。"""
    assert looks_like_db_failure(_DB_NO_CREATE_PRIV)


def test_auto_create_failure_is_db_failure():
    """自动建库/初始化表结构失败（DatabaseBootstrapConfig 中文原因）→ 弹配置页。"""
    assert looks_like_db_failure(_DB_AUTO_CREATE_FAIL)
    assert looks_like_db_failure(_DB_AUTO_INIT_FAIL)


def test_empty_console_is_not_db_failure():
    assert not looks_like_db_failure("")


# ---------- db.properties 生成 ----------

def test_render_has_db_properties_shape():
    text = render_db_properties("jdbc:mysql://localhost:3306/spore_cms" + URL_SUFFIX,
                                "root", "pw")
    assert "db.url=jdbc:mysql://localhost:3306/spore_cms" in text
    assert "db.username=root" in text
    assert "db.password=pw" in text
    assert "spring:" not in text          # 不再是 Boot 的 YAML 形状
    assert "datasource" not in text


def test_render_escapes_backslash_in_password():
    """反斜杠必须转义：Java Properties 里单个 ``\\`` 会把下一个字符吃掉，
    口令带反斜杠时就变成「配置改对了也连不上库」。"""
    text = render_db_properties("jdbc:mysql://localhost:3306/db", "root", r"a\b")
    assert "db.password=a\\\\b" in text


def test_render_keeps_colon_and_hash_literal():
    """值位置里 ``:``/``#``/引号都不用转——分隔符只认行里第一个 ``=``。"""
    text = render_db_properties("jdbc:mysql://localhost:3306/db", "root",
                                'p#w:ss"ord')
    assert 'db.password=p#w:ss"ord' in text


def test_render_roundtrips_url():
    url = "jdbc:mysql://192.168.1.9:3307/my_db" + URL_SUFFIX
    assert url in render_db_properties(url, "u", "p")


# ---------- 原子写 ----------

def test_write_creates_file_and_no_tmp_left(tmp_path):
    p = tmp_path / "db.properties"
    write_db_properties(p, "jdbc:mysql://localhost:3306/spore_cms", "root", "pw")
    assert p.is_file()
    assert not (tmp_path / "db.properties.tmp").exists()


def test_write_creates_parent_dirs(tmp_path):
    p = tmp_path / "deep" / "nested" / "db.properties"
    write_db_properties(p, "jdbc:mysql://localhost:3306/spore_cms", "root", "pw")
    assert p.is_file()


def test_write_preserves_password_exactly(tmp_path):
    p = tmp_path / "db.properties"
    write_db_properties(p, "jdbc:mysql://localhost:3306/spore_cms", "root",
                        '中文 口令 :#"x')
    text = p.read_text(encoding="utf-8")
    # 写进去再读出来必须原样（值位置不转义这些字符），不能丢字符
    assert 'db.password=中文 口令 :#"x' in text


# ---------- 旧配置预填 ----------

def test_parse_reads_host_port_db_user():
    text = ("db.url=jdbc:mysql://db.host:3307/graded_db?useUnicode=true\n"
            "db.username=admin\n"
            "db.password=x\n")
    out = parse_db_properties(text)
    assert out["host"] == "db.host"
    assert out["port"] == "3307"
    assert out["database"] == "graded_db"
    assert out["username"] == "admin"


def test_parse_empty_falls_back_to_defaults():
    assert parse_db_properties("") == DEFAULTS


def test_parse_partial_keeps_defaults_for_missing():
    out = parse_db_properties("db.url=jdbc:mysql://h:3306/db\n")
    assert out["host"] == "h"
    assert out["username"] == DEFAULTS["username"]  # 没写 username → 回落


# ---------- 写入位置（写哪儿 = config_args 读哪儿） ----------

def test_config_path_release_is_beside_war(tmp_path):
    """发行态：后端 config_args 读 war 同目录 → 配置页必须写同一处。"""
    from types import SimpleNamespace

    war = tmp_path / "spore-backend-1.3.2.war"
    war.write_bytes(b"")
    assert config_path_for(SimpleNamespace(war=war)) == (tmp_path / "db.properties")


def test_config_path_dev_mode_is_repo_root(tmp_path):
    """开发态：war 在 target/ → launch 是仓库根，配置页写仓库根那份 db.properties，
    否则改了后端不读、等于白写。"""
    from types import SimpleNamespace

    repo = tmp_path
    target = repo / "target"
    target.mkdir()
    war = target / "spore-gui.war"
    war.write_bytes(b"")

    assert config_path_for(SimpleNamespace(war=war)) == (repo / "db.properties")


def test_config_path_matches_where_config_args_reads(tmp_path):
    """核心契约：配置页写入位置 === config_args 告诉后端读的那个文件。

    1.3.2 修 Program Files 时把 config_args 改成「绝对路径指向 launch（war 目录）」，
    配置页若仍写 runtime_base（cwd，Program Files 下被迁到 SPORE_HOME）就会写错地方。
    这条钉住两者永远一致。
    """
    from types import SimpleNamespace

    from spore_client.backend import config_args

    # 发行态
    rel = tmp_path / "rel"
    rel.mkdir()
    war = rel / "spore-backend-1.3.2.war"
    war.write_bytes(b"")
    (rel / "db.properties").write_text("db.password=x", encoding="utf-8")
    written = config_path_for(SimpleNamespace(war=war))
    assert written == rel / "db.properties"
    assert config_args(rel) == [
        f"-Dspore.config={(rel / 'db.properties').resolve()}"]
    assert written.parent == rel   # 写进 launch，config_args 也读 launch

    # 开发态：war 在 target/ → launch = 仓库根
    dev = tmp_path / "dev"
    (dev / "target").mkdir(parents=True)
    dev_war = dev / "target" / "spore-gui.war"
    dev_war.write_bytes(b"")
    (dev / "db.properties").write_text("db.password=x", encoding="utf-8")
    written = config_path_for(SimpleNamespace(war=dev_war))
    assert written == dev / "db.properties"
    assert config_args(dev) == [
        f"-Dspore.config={(dev / 'db.properties').resolve()}"]


def test_config_path_none_when_no_war():
    from types import SimpleNamespace

    assert config_path_for(SimpleNamespace(war=None)) is None
