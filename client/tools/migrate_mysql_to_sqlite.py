r"""一次性迁移：旧 MySQL ``spore_cms`` → 本机 ``spore.db``（SQLite）。

只搬**存活行**（``deleted=0``）：墓碑与 user/role/permission/op_log 只为旧的登录与
手机同步服务，2026-11-13 起这两层已下线，搬过来只是垃圾。
多用户（uid 3 + uid 4）合并成单用户命名空间——桌面端现在没有账号概念。

用法（在 client/ 下）：

    .venv/Scripts/python.exe tools/migrate_mysql_to_sqlite.py            # 目标默认 LOCALAPPDATA
    .venv/Scripts/python.exe tools/migrate_mysql_to_sqlite.py --db C:\tmp\x.db --force

前置：仓库根 ``db.properties`` 里的 MySQL 口令（只读，不打印）。源库只读，绝不改。
目标已存在时先复制成 ``*.bak``（``--force`` 才覆盖）。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[1]
REPO = CLIENT.parent
sys.path.insert(0, str(CLIENT))

from spore_client.store import DEFAULT_DB, SCHEMA, SCHEMA_VERSION, TZ, fmt_time  # noqa: E402


def _props(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().replace("\\\\", "\\")
    return out


def _ms(dt: datetime | None) -> int:
    if dt is None:
        return 0
    return int(dt.replace(tzinfo=TZ).timestamp() * 1000)


def _roundtrip(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:23] if dt else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--force", action="store_true", help="目标已存在时备份后覆盖")
    args = ap.parse_args()
    db_path = Path(args.db)

    cfg = _props(REPO / "db.properties")
    if "db.password" not in cfg:
        print("缺仓库根 db.properties（db.password）", file=sys.stderr)
        return 2
    import pymysql  # 只在迁移机上需要

    src = pymysql.connect(
        host="127.0.0.1", user=cfg.get("db.username", "root"),
        password=cfg["db.password"], database="spore_cms",
        charset="utf8mb4", connect_timeout=5)
    cur = src.cursor()
    cur.execute("SELECT id, parent_id, name, sort_order, status,"
                " created_time, update_time FROM category WHERE deleted = 0")
    cats = cur.fetchall()
    cur.execute("SELECT id, category_id, title, content, fav, status,"
                " audit_status, origin, created_time, update_time"
                " FROM article WHERE deleted = 0")
    arts = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM article WHERE deleted = 1")
    dead_arts = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM category WHERE deleted = 1")
    dead_cats = cur.fetchone()[0]
    src.close()

    if db_path.exists():
        if not args.force:
            print(f"目标已存在：{db_path}（加 --force 备份后覆盖）", file=sys.stderr)
            return 2
        backup = db_path.with_suffix(db_path.suffix + ".bak")
        shutil.copy2(db_path, backup)
        print(f"已备份旧目标 → {backup}")

    tmp = db_path.with_suffix(db_path.suffix + ".tmp")
    for p in (tmp, tmp.with_name(tmp.name + "-wal"), tmp.with_name(tmp.name + "-shm")):
        p.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    with conn:
        for c in cats:
            conn.execute(
                "INSERT INTO category (id, parent_id, name, sort_order, status,"
                " created_time, update_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (c[0], c[1], c[2], c[3] or 0, c[4] if c[4] is not None else 1,
                 _ms(c[5]), _ms(c[6])))
        for a in arts:
            conn.execute(
                "INSERT INTO article (id, category_id, title, content, fav,"
                " status, audit_status, origin, created_time, update_time)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (a[0], a[1], a[2], a[3], int(bool(a[4])), a[5] or "done",
                 a[6] if a[6] is not None else 1, a[7] or "gui",
                 _ms(a[8]), _ms(a[9])))

    # ---- 对账：行数、正文逐字、时间戳往返、归属完整性 ----
    problems: list[str] = []
    got_arts = conn.execute("SELECT COUNT(*) FROM article").fetchone()[0]
    got_cats = conn.execute("SELECT COUNT(*) FROM category").fetchone()[0]
    if got_arts != len(arts):
        problems.append(f"文章行数 {got_arts} != {len(arts)}")
    if got_cats != len(cats):
        problems.append(f"科目行数 {got_cats} != {len(cats)}")
    src_hash = {a[0]: hashlib.sha256(a[3].encode()).hexdigest() for a in arts}
    db_hash = {r[0]: hashlib.sha256(r[1].encode()).hexdigest()
               for r in conn.execute("SELECT id, content FROM article")}
    if src_hash != db_hash:
        problems.append("正文 sha256 不一致")
    for a in arts:
        ms = _ms(a[9])
        if fmt_time(ms) != _roundtrip(a[9]):
            problems.append(f"update_time 往返失败：{a[0]}")
            break
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    if problems:
        print("校验失败：\n- " + "\n- ".join(problems), file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return 1

    os.replace(tmp, db_path)
    with sqlite3.connect(db_path) as check:
        dangling = check.execute(
            "SELECT COUNT(*) FROM article a WHERE a.category_id IS NOT NULL"
            " AND NOT EXISTS (SELECT 1 FROM category c WHERE c.id = a.category_id)"
        ).fetchone()[0]
        favs = check.execute("SELECT COUNT(*) FROM article WHERE fav = 1").fetchone()[0]
        owned = check.execute(
            "SELECT COUNT(*) FROM article WHERE category_id IS NOT NULL").fetchone()[0]
    print(f"OK  {db_path}")
    print(f"    articles={got_arts} categories={got_cats} fav={favs}"
          f" categorized={owned} dangling={dangling}")
    print(f"    skipped tombstones: articles={dead_arts} categories={dead_cats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
