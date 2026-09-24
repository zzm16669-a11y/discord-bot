"""
migrate_json_to_sqlite.py — سكربت هجرة لمرة وحدة بس.

يحول بياناتك الحالية من ملفات JSON (economy.json, warns.json, jail_data.json,
removed_roles.json, game_stats.json, shop_active.json) إلى قاعدة بيانات SQLite
الجديدة (bot_data.db اللي يبنيها db.py).

طريقة التشغيل:
  1. حط db.py وهذا الملف بجنب ملف البوت (بنفس المجلد اللي فيه ملفات الـ JSON).
  2. شغّل مرة وحدة بس:  python migrate_json_to_sqlite.py
  3. بعد ما تتأكد إن البوت يشتغل صح على قاعدة البيانات الجديدة، تقدر تحتفظ
     بملفات الـ JSON كنسخة احتياطية أو تحذفها — مو محتاجها بعد كذا.

ملاحظة: السكربت آمن لو شغّلته أكثر من مرة (يستخدم UPSERT للبيانات اللي مفتاحها
وحيد زي الرصيد، وللتنبيهات يضيفها زيادة لو شغّلته مرتين — فلا تشغّله إلا مرة وحدة).
"""
import json
import os
from datetime import datetime, timezone

import db


def load_json(path: str) -> dict:
    if not os.path.exists(path):
        print(f"⏭️  {path} مو موجود، تخطيته.")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            print(f"⚠️  {path} فيه خطأ بالصيغة، تخطيته.")
            return {}


def migrate_economy():
    data = load_json("economy.json")
    count = 0
    for gid, users in data.items():
        for key, value in users.items():
            if key.endswith("_last_daily"):
                uid = key[: -len("_last_daily")]
                db._conn.execute(
                    "INSERT INTO economy (guild_id, user_id, last_daily) VALUES (?,?,?) "
                    "ON CONFLICT(guild_id,user_id) DO UPDATE SET last_daily=excluded.last_daily",
                    (gid, uid, value),
                )
            elif key.endswith("_daily_game_start"):
                uid = key[: -len("_daily_game_start")]
                db._conn.execute(
                    "INSERT INTO economy (guild_id, user_id, daily_game_start) VALUES (?,?,?) "
                    "ON CONFLICT(guild_id,user_id) DO UPDATE SET daily_game_start=excluded.daily_game_start",
                    (gid, uid, value),
                )
            elif key.endswith("_daily_game_earned"):
                uid = key[: -len("_daily_game_earned")]
                db._conn.execute(
                    "INSERT INTO economy (guild_id, user_id, daily_game_earned) VALUES (?,?,?) "
                    "ON CONFLICT(guild_id,user_id) DO UPDATE SET daily_game_earned=excluded.daily_game_earned",
                    (gid, uid, value),
                )
            elif key.isdigit():
                uid = key
                db._conn.execute(
                    "INSERT INTO economy (guild_id, user_id, balance) VALUES (?,?,?) "
                    "ON CONFLICT(guild_id,user_id) DO UPDATE SET balance=excluded.balance",
                    (gid, uid, value),
                )
                count += 1
    db._conn.commit()
    print(f"✅ economy.json: تم نقل {count} رصيد.")


def migrate_warns():
    data = load_json("warns.json")
    count = 0
    for gid, users in data.items():
        for uid, warns in users.items():
            for w in warns:
                db._conn.execute(
                    "INSERT INTO warns (guild_id, user_id, number, reason, moderator_id, timestamp) "
                    "VALUES (?,?,?,?,?,?)",
                    (gid, uid, w["number"], w.get("reason"), str(w.get("moderator_id")), w.get("timestamp")),
                )
                count += 1
    db._conn.commit()
    print(f"✅ warns.json: تم نقل {count} تنبيه.")


def migrate_jail():
    data = load_json("jail_data.json")
    count = 0
    for gid, users in data.items():
        for uid, role_ids in users.items():
            db._conn.execute(
                "INSERT INTO jail (guild_id, user_id, role_ids) VALUES (?,?,?) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET role_ids=excluded.role_ids",
                (gid, uid, json.dumps(role_ids)),
            )
            count += 1
    db._conn.commit()
    print(f"✅ jail_data.json: تم نقل {count} سجل.")


def migrate_removed_roles():
    data = load_json("removed_roles.json")
    count = 0
    for gid, users in data.items():
        for uid, role_id in users.items():
            db._conn.execute(
                "INSERT INTO removed_roles (guild_id, user_id, role_id) VALUES (?,?,?) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET role_id=excluded.role_id",
                (gid, uid, role_id),
            )
            count += 1
    db._conn.commit()
    print(f"✅ removed_roles.json: تم نقل {count} سجل.")


def migrate_game_stats():
    data = load_json("game_stats.json")
    count = 0
    for gid, users in data.items():
        for uid, stats in users.items():
            db._conn.execute(
                "INSERT INTO game_stats (guild_id, user_id, wins, losses) VALUES (?,?,?,?) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET wins=excluded.wins, losses=excluded.losses",
                (gid, uid, stats.get("wins", 0), stats.get("losses", 0)),
            )
            count += 1
    db._conn.commit()
    print(f"✅ game_stats.json: تم نقل {count} سجل.")


def migrate_shop_active():
    data = load_json("shop_active.json")
    count = 0
    for gid, users in data.items():
        for uid, entry in users.items():
            entry = dict(entry)
            item_type = entry.pop("type", "unknown")
            expires = entry.pop("expires", datetime.now(timezone.utc).isoformat())
            db._conn.execute(
                "INSERT INTO shop_active (guild_id, user_id, item_type, expires, extra) VALUES (?,?,?,?,?) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET item_type=excluded.item_type, "
                "expires=excluded.expires, extra=excluded.extra",
                (gid, uid, item_type, expires, json.dumps(entry)),
            )
            count += 1
    db._conn.commit()
    print(f"✅ shop_active.json: تم نقل {count} سجل.")


if __name__ == "__main__":
    migrate_economy()
    migrate_warns()
    migrate_jail()
    migrate_removed_roles()
    migrate_game_stats()
    migrate_shop_active()
    print("\n🎉 خلصت الهجرة! صار عندك bot_data.db فيه كل بياناتك القديمة.")
