"""db_config 契约：DB 失败识别 / yml 生成+原子写 / 旧配置预填 / 写入位置。

这些是纯逻辑，不碰 Qt——配置页 UI 只是把它们串起来。
"""

from spore_client.db_config import (  # noqa: F401 — qapp 触发 Qt offscreen 初始化
    DEFAULTS,
    URL_SUFFIX,
    config_path_for,
    looks_like_db_failure,
    parse_local_yml,
    render_local_yml,
    write_local_yml,
)

# 真实 HikariCP 秒退日志里抓的片段（2026-10-29 实测）
_DB_DENIED = ("HikariPool-1 - Exception during pool initialization.\n"
              "java.sql.SQLException: Access denied for user 'root'@'localhost'")
_DB_UNREACHABLE = ("### Cause: org.springframework.jdbc."
                   "CannotGetJdbcConnectionException: Failed to obtain JDBC "
                   "Connection")
_NOT_DB_MISSING_JAR = "没找到后端 jar（spore-backend-*.jar）"
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


def test_missing_jar_is_not_db_failure():
    """缺 jar 也「后端起不来」，但绝不能弹数据库配置页——判据要精准。"""
    assert not looks_like_db_failure(_NOT_DB_MISSING_JAR)


def test_missing_java_is_not_db_failure():
    """缺 Java 同理：不是数据库问题，弹配置页没意义（填了也起不来）。"""
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


# ---------- yml 生成 ----------

def test_render_has_spring_datasource_shape():
    text = render_local_yml("jdbc:mysql://localhost:3306/spore_cms" + URL_SUFFIX,
                            "root", "pw")
    assert "spring:" in text
    assert "  datasource:" in text
    assert "    url: " in text
    assert "    username: " in text
    assert "    password: " in text


def test_render_quotes_password_with_special_chars():
    """含 `:`/`#`/引号的口令必须被引号包住，否则 yml 语法错、后端起不来。"""
    text = render_local_yml("jdbc:mysql://localhost:3306/db", "root",
                            'p#w:ss"ord')
    assert 'password: "p#w:ss\\"ord"' in text


def test_render_roundtrips_url():
    url = "jdbc:mysql://192.168.1.9:3307/my_db" + URL_SUFFIX
    assert url in render_local_yml(url, "u", "p")


# ---------- 原子写 ----------

def test_write_creates_file_and_no_tmp_left(tmp_path):
    p = tmp_path / "application-local.yml"
    write_local_yml(p, "jdbc:mysql://localhost:3306/spore_cms", "root", "pw")
    assert p.is_file()
    assert not (tmp_path / "application-local.yml.tmp").exists()


def test_write_creates_parent_dirs(tmp_path):
    p = tmp_path / "deep" / "nested" / "application-local.yml"
    write_local_yml(p, "jdbc:mysql://localhost:3306/spore_cms", "root", "pw")
    assert p.is_file()


def test_write_preserves_password_exactly(tmp_path):
    p = tmp_path / "application-local.yml"
    write_local_yml(p, "jdbc:mysql://localhost:3306/spore_cms", "root",
                    "中文 口令 :#\"x")
    text = p.read_text(encoding="utf-8")
    # 写进去再读出来必须原样（双引号转义），不能丢字符
    assert 'password: "中文 口令 :#\\"x"' in text


# ---------- 旧配置预填 ----------

def test_parse_reads_host_port_db_user():
    text = ('spring:\n  datasource:\n    url: "jdbc:mysql://db.host:3307/'
            'graded_db?useUnicode=true"\n    username: "admin"\n'
            '    password: "x"\n')
    out = parse_local_yml(text)
    assert out["host"] == "db.host"
    assert out["port"] == "3307"
    assert out["database"] == "graded_db"
    assert out["username"] == "admin"


def test_parse_empty_falls_back_to_defaults():
    assert parse_local_yml("") == DEFAULTS


def test_parse_partial_keeps_defaults_for_missing():
    out = parse_local_yml('    url: "jdbc:mysql://h:3306/db"\n')
    assert out["host"] == "h"
    assert out["username"] == DEFAULTS["username"]  # 没写 username → 回落


# ---------- 写入位置（写哪儿 = config_args 读哪儿） ----------

def test_config_path_release_is_beside_jar(tmp_path):
    """发行态：后端 config_args 读 jar 同目录 → 配置页必须写同一处。"""
    from types import SimpleNamespace

    jar = tmp_path / "spore-backend-1.3.2.jar"
    jar.write_bytes(b"")
    assert config_path_for(SimpleNamespace(jar=jar)) == (
        tmp_path / "application-local.yml")


def test_config_path_dev_mode_points_at_src_resources(tmp_path):
    """开发态：config_args 优先读 src/main/resources → 配置页写同一处，
    否则改了后端不读、等于白写。"""
    from types import SimpleNamespace

    repo = tmp_path
    target = repo / "target"
    target.mkdir()
    (target / "spore-gui-0.1.0-SNAPSHOT.jar").write_bytes(b"")
    res = repo / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application-local.yml").write_text("x", encoding="utf-8")

    assert config_path_for(
        SimpleNamespace(jar=target / "spore-gui-0.1.0-SNAPSHOT.jar")) == (
        res / "application-local.yml")


def test_config_path_neither_present_falls_to_jar_dir(tmp_path):
    """两处都没 yml（全新装机）→ 落 jar 同目录；写完重启后 config_args 就能发现它。"""
    from types import SimpleNamespace

    jar = tmp_path / "spore-backend-1.3.2.jar"
    jar.write_bytes(b"")
    assert config_path_for(SimpleNamespace(jar=jar)) == (
        tmp_path / "application-local.yml")


def test_config_path_matches_where_config_args_reads(tmp_path):
    """核心契约：配置页写入位置 === config_args 解析出的 Spring 读取目录。

    1.3.2 修 Program Files 时把 config_args 改成「绝对路径指向 launch（jar 目录）」，
    配置页若仍写 runtime_base（cwd，Program Files 下被迁到 SPORE_HOME）就会写错地方。
    这条钉住两者永远一致。
    """
    from types import SimpleNamespace

    from spore_client.backend import config_args

    # 发行态：jar 同目录有 yml
    rel = tmp_path / "rel"
    rel.mkdir()
    (rel / "spore-backend-1.3.2.jar").write_bytes(b"")
    (rel / "application-local.yml").write_text("spring: {}", encoding="utf-8")
    written = config_path_for(SimpleNamespace(jar=rel / "spore-backend-1.3.2.jar"))
    read_dir = config_args(rel)
    assert read_dir == [
        "--spring.config.additional-location=optional:file:"
        + rel.resolve().as_posix() + "/"]
    assert written.parent == rel   # 写进 launch，config_args 也读 launch

    # 开发态：src/main/resources 有 yml
    dev = tmp_path / "dev"
    (dev / "target").mkdir(parents=True)
    (dev / "target" / "spore-gui-0.1.0-SNAPSHOT.jar").write_bytes(b"")
    res = dev / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application-local.yml").write_text("spring: {}", encoding="utf-8")
    written = config_path_for(
        SimpleNamespace(jar=dev / "target" / "spore-gui-0.1.0-SNAPSHOT.jar"))
    read_dir = config_args(dev)
    assert read_dir == [
        "--spring.config.additional-location=optional:file:"
        + res.resolve().as_posix() + "/"]
    assert written.parent == res    # 写进 src/main/resources，config_args 也读它


def test_config_path_none_when_no_jar():
    from types import SimpleNamespace

    assert config_path_for(SimpleNamespace(jar=None)) is None
