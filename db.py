"""
db.py — طبقة قاعدة بيانات SQLite تستبدل ملفات JSON (economy.json, warns.json,
jail_data.json, removed_roles.json, game_stats.json, shop_active.json).

الفايدة: بدل ما كل أمر يفتح الملف كامل ويقرأه ويعيد كتابته من الصفر، هذي
الطبقة تسوي عمليات SQL صغيرة وسريعة على قاعدة بيانات وحدة (bot_data.db).

الاستخدام ببوتك: بس حط هذا الملف بجنب ملف البوت، وسوي:
    import db as _db
وبعدها استبدل جسم دوال زي get_balance/add_balance بس تنادي _db.get_balance/...
(التفاصيل والأمثلة موجودة بالرسالة اللي معاك).
"""
import json
import sqlite3
import threading
from datetime import datetime, timezone

DB_PATH = "bot_data.db"

_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.execute("PRAGMA journal_mode=WAL")
_conn.row_factory = sqlite3.Row


def _init():
    with _lock:
        _conn.executescript("""
        CREATE TABLE IF NOT EXISTS economy (
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            balance INTEGER NOT NULL DEFAULT 0,
            last_daily TEXT,
            daily_game_start TEXT,
            daily_game_earned INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            number INTEGER NOT NULL,
            reason TEXT,
            moderator_id TEXT,
            timestamp TEXT
        );

        CREATE TABLE IF NOT EXISTS jail (
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role_ids TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS removed_roles (
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS game_stats (
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS shop_active (
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            item_type TEXT NOT NULL,
            expires TEXT NOT NULL,
            extra TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS tickets (
            channel_id TEXT PRIMARY KEY,
            guild_id TEXT NOT NULL,
            opener_id TEXT NOT NULL,
            ticket_type TEXT NOT NULL,
            number INTEGER NOT NULL,
            claimed_by TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ticket_counters (
            guild_id TEXT PRIMARY KEY,
            last_number INTEGER NOT NULL DEFAULT 0
        );
        """)
        _conn.commit()


_init()


def _ensure_economy_row(gid: str, uid: str):
    _conn.execute(
        "INSERT OR IGNORE INTO economy (guild_id, user_id) VALUES (?, ?)", (gid, uid)
    )


# ============================================================
# الاقتصاد / النقاط
# ============================================================
def get_balance(guild_id: int, user_id: int) -> int:
    with _lock:
        row = _conn.execute(
            "SELECT balance FROM economy WHERE guild_id=? AND user_id=?",
            (str(guild_id), str(user_id)),
        ).fetchone()
    return row["balance"] if row else 0


def add_balance(guild_id: int, user_id: int, amount: int) -> int:
    gid, uid = str(guild_id), str(user_id)
    with _lock:
        _ensure_economy_row(gid, uid)
        _conn.execute(
            "UPDATE economy SET balance = balance + ? WHERE guild_id=? AND user_id=?",
            (amount, gid, uid),
        )
        _conn.commit()
        row = _conn.execute(
            "SELECT balance FROM economy WHERE guild_id=? AND user_id=?", (gid, uid)
        ).fetchone()
    return row["balance"]


def get_last_daily(guild_id: int, user_id: int) -> str | None:
    with _lock:
        row = _conn.execute(
            "SELECT last_daily FROM economy WHERE guild_id=? AND user_id=?",
            (str(guild_id), str(user_id)),
        ).fetchone()
    return row["last_daily"] if row else None


def set_last_daily(guild_id: int, user_id: int, when_iso: str) -> None:
    gid, uid = str(guild_id), str(user_id)
    with _lock:
        _ensure_economy_row(gid, uid)
        _conn.execute(
            "UPDATE economy SET last_daily=? WHERE guild_id=? AND user_id=?",
            (when_iso, gid, uid),
        )
        _conn.commit()


def add_game_reward(guild_id: int, user_id: int, amount: int, cap: int = 500) -> int:
    """يضيف نقاط من مكاسب الألعاب بحد أقصى `cap` نقطة كل 24 ساعة. يرجع المبلغ اللي انضاف فعليًا."""
    if amount <= 0:
        return 0
    gid, uid = str(guild_id), str(user_id)
    now = datetime.now(timezone.utc)
    with _lock:
        _ensure_economy_row(gid, uid)
        row = _conn.execute(
            "SELECT daily_game_start, daily_game_earned FROM economy WHERE guild_id=? AND user_id=?",
            (gid, uid),
        ).fetchone()
        start_str, earned = row["daily_game_start"], row["daily_game_earned"] or 0
        if not start_str or (now - datetime.fromisoformat(start_str)).total_seconds() >= 86400:
            start_str = now.isoformat()
            earned = 0
        actual = max(0, min(amount, cap - earned))
        _conn.execute(
            "UPDATE economy SET balance = balance + ?, daily_game_start=?, daily_game_earned=? "
            "WHERE guild_id=? AND user_id=?",
            (actual, start_str, earned + actual, gid, uid),
        )
        _conn.commit()
    return actual


def get_leaderboard(guild_id: int, limit: int = 10) -> list[tuple[int, int]]:
    with _lock:
        rows = _conn.execute(
            "SELECT user_id, balance FROM economy WHERE guild_id=? AND balance > 0 "
            "ORDER BY balance DESC LIMIT ?",
            (str(guild_id), limit),
        ).fetchall()
    return [(int(r["user_id"]), r["balance"]) for r in rows]


# ============================================================
# التنبيهات
# ============================================================
def add_warn(guild_id: int, member_id: int, reason: str, moderator_id: int) -> int:
    gid, mid = str(guild_id), str(member_id)
    with _lock:
        row = _conn.execute(
            "SELECT COUNT(*) AS c FROM warns WHERE guild_id=? AND user_id=?", (gid, mid)
        ).fetchone()
        warn_number = row["c"] + 1
        _conn.execute(
            "INSERT INTO warns (guild_id, user_id, number, reason, moderator_id, timestamp) "
            "VALUES (?,?,?,?,?,?)",
            (gid, mid, warn_number, reason, str(moderator_id), datetime.now(timezone.utc).isoformat()),
        )
        _conn.commit()
    return warn_number


def get_warn_count(guild_id: int, member_id: int) -> int:
    with _lock:
        row = _conn.execute(
            "SELECT COUNT(*) AS c FROM warns WHERE guild_id=? AND user_id=?",
            (str(guild_id), str(member_id)),
        ).fetchone()
    return row["c"]


def pop_oldest_warn(guild_id: int, member_id: int) -> bool:
    """يحذف أقدم تنبيه لعضو (يستخدمه .شراء تنظيف). يرجع True لو كان فيه تنبيه يحذفه."""
    gid, mid = str(guild_id), str(member_id)
    with _lock:
        row = _conn.execute(
            "SELECT id FROM warns WHERE guild_id=? AND user_id=? ORDER BY number ASC LIMIT 1",
            (gid, mid),
        ).fetchone()
        if row is None:
            return False
        _conn.execute("DELETE FROM warns WHERE id=?", (row["id"],))
        _conn.commit()
    return True


# ============================================================
# إحصائيات الألعاب
# ============================================================
def record_game_result(guild_id: int, user_id: int, won: bool) -> None:
    gid, uid = str(guild_id), str(user_id)
    col = "wins" if won else "losses"
    with _lock:
        _conn.execute(
            f"INSERT INTO game_stats (guild_id, user_id, {col}) VALUES (?, ?, 1) "
            f"ON CONFLICT(guild_id, user_id) DO UPDATE SET {col} = {col} + 1",
            (gid, uid),
        )
        _conn.commit()


def get_game_stats(guild_id: int, user_id: int) -> dict:
    with _lock:
        row = _conn.execute(
            "SELECT wins, losses FROM game_stats WHERE guild_id=? AND user_id=?",
            (str(guild_id), str(user_id)),
        ).fetchone()
    return {"wins": row["wins"], "losses": row["losses"]} if row else {"wins": 0, "losses": 0}


# ============================================================
# السجن (jail)
# ============================================================
def save_jail_roles(guild_id: int, user_id: int, role_ids: list[int]) -> None:
    gid, uid = str(guild_id), str(user_id)
    with _lock:
        _conn.execute(
            "INSERT INTO jail (guild_id, user_id, role_ids) VALUES (?,?,?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET role_ids=excluded.role_ids",
            (gid, uid, json.dumps(role_ids)),
        )
        _conn.commit()


def get_jail_roles(guild_id: int, user_id: int) -> list[int]:
    with _lock:
        row = _conn.execute(
            "SELECT role_ids FROM jail WHERE guild_id=? AND user_id=?",
            (str(guild_id), str(user_id)),
        ).fetchone()
    return json.loads(row["role_ids"]) if row else []


def clear_jail_roles(guild_id: int, user_id: int) -> None:
    with _lock:
        _conn.execute(
            "DELETE FROM jail WHERE guild_id=? AND user_id=?",
            (str(guild_id), str(user_id)),
        )
        _conn.commit()


# ============================================================
# الرتب المسحوبة (تنزيل / رجع)
# ============================================================
def save_removed_role(guild_id: int, user_id: int, role_id: int) -> None:
    gid, uid = str(guild_id), str(user_id)
    with _lock:
        _conn.execute(
            "INSERT INTO removed_roles (guild_id, user_id, role_id) VALUES (?,?,?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET role_id=excluded.role_id",
            (gid, uid, role_id),
        )
        _conn.commit()


def get_removed_role(guild_id: int, user_id: int) -> int | None:
    with _lock:
        row = _conn.execute(
            "SELECT role_id FROM removed_roles WHERE guild_id=? AND user_id=?",
            (str(guild_id), str(user_id)),
        ).fetchone()
    return row["role_id"] if row else None


def clear_removed_role(guild_id: int, user_id: int) -> None:
    with _lock:
        _conn.execute(
            "DELETE FROM removed_roles WHERE guild_id=? AND user_id=?",
            (str(guild_id), str(user_id)),
        )
        _conn.commit()


# ============================================================
# المتجر (لقب/لون مؤقت)
# ============================================================
def set_shop_active(guild_id: int, user_id: int, item_type: str, expires_iso: str, extra: dict) -> None:
    gid, uid = str(guild_id), str(user_id)
    with _lock:
        _conn.execute(
            "INSERT INTO shop_active (guild_id, user_id, item_type, expires, extra) VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET item_type=excluded.item_type, "
            "expires=excluded.expires, extra=excluded.extra",
            (gid, uid, item_type, expires_iso, json.dumps(extra)),
        )
        _conn.commit()


def clear_shop_active(guild_id: int, user_id: int) -> dict | None:
    """يحذف السجل ويرجعه (يستخدمه .شراء لقب لو كان عنده لقب سابق يبدّله)."""
    gid, uid = str(guild_id), str(user_id)
    with _lock:
        row = _conn.execute(
            "SELECT item_type, expires, extra FROM shop_active WHERE guild_id=? AND user_id=?",
            (gid, uid),
        ).fetchone()
        if row is None:
            return None
        _conn.execute("DELETE FROM shop_active WHERE guild_id=? AND user_id=?", (gid, uid))
        _conn.commit()
    entry = json.loads(row["extra"])
    entry["type"] = row["item_type"]
    entry["expires"] = row["expires"]
    return entry


def get_all_shop_active() -> list[dict]:
    """للمهمة الدورية (shop_expiry_task) — ترجع كل السجلات النشطة بكل السيرفرات."""
    with _lock:
        rows = _conn.execute("SELECT guild_id, user_id, item_type, expires, extra FROM shop_active").fetchall()
    result = []
    for r in rows:
        entry = json.loads(r["extra"])
        entry.update({
            "guild_id": r["guild_id"], "user_id": r["user_id"],
            "type": r["item_type"], "expires": r["expires"],
        })
        result.append(entry)
    return result


def remove_shop_active(guild_id, user_id) -> None:
    with _lock:
        _conn.execute(
            "DELETE FROM shop_active WHERE guild_id=? AND user_id=?",
            (str(guild_id), str(user_id)),
        )
        _conn.commit()


# ============================================================
# التكتات
# ============================================================
def next_ticket_number(guild_id: int) -> int:
    """يرجع رقم تكت جديد (متسلسل لكل سيرفر لحاله)."""
    gid = str(guild_id)
    with _lock:
        _conn.execute(
            "INSERT INTO ticket_counters (guild_id, last_number) VALUES (?, 1) "
            "ON CONFLICT(guild_id) DO UPDATE SET last_number = last_number + 1",
            (gid,),
        )
        _conn.commit()
        row = _conn.execute(
            "SELECT last_number FROM ticket_counters WHERE guild_id=?", (gid,)
        ).fetchone()
    return row["last_number"]


def create_ticket(guild_id: int, channel_id: int, opener_id: int, ticket_type: str, number: int) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO tickets (channel_id, guild_id, opener_id, ticket_type, number, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (str(channel_id), str(guild_id), str(opener_id), ticket_type, number,
             datetime.now(timezone.utc).isoformat()),
        )
        _conn.commit()


def get_ticket(channel_id: int) -> dict | None:
    with _lock:
        row = _conn.execute(
            "SELECT * FROM tickets WHERE channel_id=?", (str(channel_id),)
        ).fetchone()
    return dict(row) if row else None


def set_ticket_claimed(channel_id: int, staff_id: int) -> None:
    with _lock:
        _conn.execute(
            "UPDATE tickets SET claimed_by=? WHERE channel_id=?",
            (str(staff_id), str(channel_id)),
        )
        _conn.commit()


def close_ticket(channel_id: int) -> None:
    with _lock:
        _conn.execute("DELETE FROM tickets WHERE channel_id=?", (str(channel_id),))
        _conn.commit()
