# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import sqlite3
import sys
import time

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "heating.db"

# Old → New mapping
KEY_MAP = {
    "MINIMUM_HEATING_STARTUP_TIME": "WARMUP_MINIMUM_LEAD_TIME",
    "MAXIMUM_HEATING_STARTUP_TIME": "WARMUP_MAXIMUM_LEAD_TIME",
    "HEATUP_RATE": "FALLBACK_HEATUP_RATE",
    "TARGET_SETPOINT_OFFSET": "WARMUP_TARGET_OFFSET",
}

# Defaults (in case old key missing)
DEFAULTS = {
    "WARMUP_MINIMUM_LEAD_TIME": "30",
    "WARMUP_MAXIMUM_LEAD_TIME": "120",
    "FALLBACK_HEATUP_RATE": "0.4",
    "WARMUP_TARGET_OFFSET": "-0.5",
}


def log(msg):
    print("[MIGRATION]", msg)


def table_exists(cursor, table_name):
    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
    """, (table_name,))
    return cursor.fetchone() is not None


def get_table_columns(cursor, table_name):
    cursor.execute("PRAGMA table_info(%s)" % table_name)
    rows = cursor.fetchall()
    return [row[1] for row in rows]


def setting_exists(cursor, key):
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    return cursor.fetchone()


def get_value(cursor, key):
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    return row[0] if row else None


def set_value(cursor, key, value):
    # Try modern UPSERT (SQLite ≥ 3.24)
    try:
        cursor.execute("""
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))
    except sqlite3.OperationalError:
        # Fallback for older SQLite: manual upsert
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        if cursor.fetchone():
            cursor.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))
        else:
            cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))


def delete_key(cursor, key):
    cursor.execute("DELETE FROM settings WHERE key = ?", (key,))


def log_state(cursor, text):
    now = time.time()
    cursor.execute("""
        INSERT INTO state_log (ts_epoch, ts, system, state)
        VALUES (?, ?, ?, ?)
    """, (
        now,
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "SYSTEM",
        text
    ))


def ensure_heatup_learning_log(cursor):
    log("Ensuring heatup_learning_log exists...")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS heatup_learning_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_ts_epoch REAL,
            ended_ts_epoch REAL,
            duration_seconds REAL,
            start_temp REAL,
            end_temp REAL,
            delta_temp REAL,
            calculated_rate REAL,
            target_temp REAL,
            warmup_enabled INTEGER,
            relay_confirmed_seconds REAL,
            valid INTEGER,
            invalid_reason TEXT,
            created_ts_epoch REAL
        )
    """)

    existing = set(get_table_columns(cursor, "heatup_learning_log"))

    wanted_columns = [
        ("start_hour", "INTEGER"),
        ("start_weekday", "INTEGER"),
        ("start_delta_temp", "REAL"),
        ("end_reason", "TEXT"),
        ("ch_switch_mode", "TEXT"),
        ("hw_was_on", "INTEGER DEFAULT 0"),
        ("sample_count_hint", "INTEGER DEFAULT 0"),
        ("confidence_hint", "REAL DEFAULT 0.0"),
    ]

    for col_name, col_def in wanted_columns:
        if col_name not in existing:
            sql = "ALTER TABLE heatup_learning_log ADD COLUMN %s %s" % (col_name, col_def)
            log("Adding column heatup_learning_log.%s" % col_name)
            cursor.execute(sql)


def ensure_warmup_outcomes(cursor):
    log("Ensuring warmup_outcomes exists...")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS warmup_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scheduled_entry_id INTEGER,
            schedule_set_name TEXT,
            started_ts_epoch REAL,
            scheduled_start_ts_epoch REAL,
            scheduled_end_ts_epoch REAL,
            scheduled_start_hour INTEGER,
            delta_band TEXT,
            target_temp REAL,
            actual_temp_at_start REAL,
            miss_temp REAL,
            predictive_rate_used REAL,
            learned_rate_used REAL,
            live_rate_used REAL,
            base_rate_used REAL,
            outcome_confidence_hint REAL,
            created_ts_epoch REAL
        )
    """)

    existing = set(get_table_columns(cursor, "warmup_outcomes"))

    wanted_columns = [
        ("scheduled_start_hour", "INTEGER"),
        ("delta_band", "TEXT"),
        ("outcome_confidence_hint", "REAL"),
    ]

    for col_name, col_def in wanted_columns:
        if col_name not in existing:
            sql = "ALTER TABLE warmup_outcomes ADD COLUMN %s %s" % (col_name, col_def)
            log("Adding column warmup_outcomes.%s" % col_name)
            cursor.execute(sql)

def ensure_cooldown_learning_log(cursor):
    log("Ensuring cooldown_learning_log exists...")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cooldown_learning_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_ts_epoch REAL,
            ended_ts_epoch REAL,
            duration_seconds REAL,
            start_temp REAL,
            end_temp REAL,
            delta_temp REAL,
            calculated_rate REAL,
            valid INTEGER,
            invalid_reason TEXT,
            end_reason TEXT,
            sample_count_hint INTEGER,
            created_ts_epoch REAL
        )
    """)

def migrate_settings(cursor):
    for old_key, new_key in KEY_MAP.items():
        old_val = get_value(cursor, old_key)
        new_exists = setting_exists(cursor, new_key)

        if new_exists:
            log("{} already exists -> skipping (idempotent)".format(new_key))
            continue

        if old_val is not None:
            log("Migrating {} -> {} (value={})".format(old_key, new_key, old_val))
            set_value(cursor, new_key, old_val)
            log_state(cursor, u"Migrated {} -> {}".format(old_key, new_key))
        else:
            default_val = DEFAULTS[new_key]
            log("{} missing -> creating {} with default ({})".format(old_key, new_key, default_val))
            set_value(cursor, new_key, default_val)
            log_state(cursor, u"Created {} with default".format(new_key))

    log("Cleaning up old keys...")
    for old_key in KEY_MAP.keys():
        if setting_exists(cursor, old_key):
            log("Removing old key: {}".format(old_key))
            delete_key(cursor, old_key)

def verify(cursor):
    log("Verification starting...")

    cursor.execute("""
        SELECT key, value
        FROM settings
        WHERE key IN (
            'WARMUP_MINIMUM_LEAD_TIME',
            'WARMUP_MAXIMUM_LEAD_TIME',
            'FALLBACK_HEATUP_RATE',
            'WARMUP_TARGET_OFFSET'
        )
        ORDER BY key
    """)
    rows = cursor.fetchall()
    log("Settings:")
    for key, value in rows:
        log("  {} = {}".format(key, value))

    for table_name in ("heatup_learning_log", "warmup_outcomes", "cooldown_learning_log"):
        if table_exists(cursor, table_name):
            cols = get_table_columns(cursor, table_name)
            log("Table {} columns: {}".format(table_name, ", ".join(cols)))

            cursor.execute("SELECT COUNT(*) FROM %s" % table_name)
            count = cursor.fetchone()[0]
            log("Table {} row count: {}".format(table_name, count))
        else:
            log("Table {} is MISSING".format(table_name))

def migrate():
    log("Opening DB: {}".format(DB_PATH))
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        migrate_settings(cursor)
        ensure_heatup_learning_log(cursor)
        ensure_warmup_outcomes(cursor)
        ensure_cooldown_learning_log(cursor)
        verify(cursor)

        conn.commit()
        log("Migration complete.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()