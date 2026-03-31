#!/usr/bin/python
# -*- coding: utf-8 -*-
# db_init.py

from __future__ import print_function
import os
import sqlite3
import time

SCHEMA_VERSION = 1

SETTINGS_SCHEMA = {
    # Central Heating
    "CH_SYSTEM_SWITCH": {
        "default": "timed",
        "type": "enum",
        "allowed": ["timed", "on", "off", "once"]
    },
    "CH_ADVANCE": {
        "default": "False",
        "type": "bool"
    },
    "CH_BOOST_FINISH_TIME": {
        "default": "00:00",
        "type": "time"
    },
    "CH_BOOST_FINISH_EPOCH": {
        "default": "0",
        "type": "int",
        "min": 0,
        "max": 2147483647
    },
    "DEFAULT_SETPOINT": {
        "default": "10.0",
        "type": "float",
        "min": 5.0,
        "max": 24.0
    },
    "DEFAULT_ON_SETPOINT": {
        "default": "20.0",
        "type": "float",
        "min": 5.0,
        "max": 24.0
    },
    "BOOST_SETPOINT": {
        "default": "21.0",
        "type": "float",
        "min": 5.0,
        "max": 24.0
    },
    "MINIMUM_HEATING_STARTUP_TIME": {
        "default": "30",
        "type": "int",
        "min": 5,
        "max": 240
    },
    "MAXIMUM_HEATING_STARTUP_TIME": {
        "default": "120",
        "type": "int",
        "min": 5,
        "max": 360
    },
    "HEATUP_RATE": {
        "default": "0.4",
        "type": "float",
        "min": 0.1,
        "max": 5.0
    },
    "TARGET_SETPOINT_OFFSET": {
        "default": "-0.5",
        "type": "float",
        "min": -5.0,
        "max": 5.0
    },
    "COMFORT": {
        "default": "True",
        "type": "bool"
    },

    # Hot Water
    "HW_SYSTEM_SWITCH": {
        "default": "timed",
        "type": "enum",
        "allowed": ["timed", "on", "off", "once"]
    },
    "HW_ADVANCE": {
        "default": "False",
        "type": "bool"
    },
    "HW_BOOST_FINISH_TIME": {
        "default": "00:00",
        "type": "time"
    },
    "HW_BOOST_FINISH_EPOCH": {
        "default": "0",
        "type": "int",
        "min": 0,
        "max": 2147483647
    },

    # System
    "LOGGING_INTERVAL": {
        "default": "600",
        "type": "int",
        "min": 10,
        "max": 86400
    },
    "ENGINE_INTERVAL": {
        "default": "2",
        "type": "int",
        "min": 1,
        "max": 60
    },
    "SENSOR_INTERVAL": {
        "default": "2",
        "type": "int",
        "min": 1,
        "max": 60
    },
    "CH_LAST_DESIRED": {
        "default": "OFF",
        "type": "enum",
        "allowed": ["ON", "OFF"]
    },
    "HW_LAST_DESIRED": {
        "default": "OFF",
        "type": "enum",
        "allowed": ["ON", "OFF"]
    },
    "CH_MIN_ON_SECONDS": {
        "default": "120",
        "type": "int",
        "min": 0,
        "max": 3600
    },
    "CH_MIN_OFF_SECONDS": {
        "default": "120",
        "type": "int",
        "min": 0,
        "max": 3600
    },

    # Calibration / Relay hardware
    "TEMP_SENSOR_ADJUSTMENT_DEGREES": {
        "default": "-4.0",  # legacy behaviour
        "type": "float",
        "min": -10.0,
        "max": 10.0
    },
    "HYSTERESIS_BAND": {
        "default": "0",  # legacy default was 0
        "type": "float",
        "min": 0.0,
        "max": 10.0
    },
    "RELAY_BOARD_DEVICE_ID": {
        "default": "RB",
        "type": "str",
        "max_len": 2
    },
    # Relay safety / mapping
    "RELAY_ENABLE": {
        "default": "False",     # SAFE DEFAULT: never switch hardware until you flip this
        "type": "bool"
    },
    "CH_RELAY_LETTER": {
        "default": "A",
        "type": "str",
        "max_len": 1
    },
    "HW_RELAY_LETTER": {
        "default": "B",
        "type": "str",
        "max_len": 1
    },
    "SENSOR_DEVICE_ID": {
        "default": "28-000007e4fecf",
        "type": "str",
        "max_len": 32
    },
    #LCD Brightness settings
    "LCD_BRIGHTNESS": {
        "default": "80",
        "type": "int",
        "min": 1,
        "max": 250
    },
    "LCD_DIM_LEVEL": {
        "default": "20",
        "type": "int",
        "min": 1,
        "max": 250
    },
    "LCD_DIM_START_TIME": {
        "default": "00:00",
        "type": "time"
    },
    "LCD_DIM_END_TIME": {
        "default": "00:00",
        "type": "time"
    }
}

def _table_exists(cur, name):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None

def ensure_overrides_and_schedules(conn):
    cur = conn.cursor()

    # -------------------------
    # Away Periods (highest priority override)
    # Suspends NORMAL schedules AND special periods
    # -------------------------
    if not _table_exists(cur, "away_periods"):
        print("[DB_INIT] Creating away_periods")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS away_periods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_ts_epoch REAL NOT NULL,
                start_ts_text TEXT NOT NULL,
                end_ts_epoch REAL NOT NULL,
                end_ts_text TEXT NOT NULL,
                systems TEXT NOT NULL,            -- 'CH', 'HW', or 'CH,HW'
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
                note TEXT,
                CHECK (end_ts_epoch > start_ts_epoch)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_away_enabled ON away_periods(enabled)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_away_time ON away_periods(start_ts_epoch, end_ts_epoch)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_away_enabled_time ON away_periods(enabled, start_ts_epoch, end_ts_epoch)")

    # -------------------------
    # Special Periods (override NORMAL weekly schedule)
    # e.g. CHRISTMAS, EASTER, SUMMER
    # Overridden by away_periods
    # -------------------------
    if not _table_exists(cur, "special_periods"):
        print("[DB_INIT] Creating special_periods")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS special_periods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_ts_epoch REAL NOT NULL,
                start_ts_text TEXT NOT NULL,
                end_ts_epoch REAL NOT NULL,
                end_ts_text TEXT NOT NULL,
                systems TEXT NOT NULL,            -- 'CH', 'HW', or 'CH,HW'
                schedule_set_name TEXT NOT NULL,  -- e.g. 'CHRISTMAS'
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
                note TEXT,
                CHECK (end_ts_epoch > start_ts_epoch)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_special_enabled ON special_periods(enabled)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_special_time ON special_periods(start_ts_epoch, end_ts_epoch)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_special_enabled_time ON special_periods(enabled, start_ts_epoch, end_ts_epoch)")

    # -------------------------
    # Schedule Sets (named groups of weekly schedules)
    # NORMAL, CHRISTMAS, etc.
    # -------------------------
    if not _table_exists(cur, "schedule_sets"):
        print("[DB_INIT] Creating schedule_sets")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schedule_sets (
                name TEXT PRIMARY KEY CHECK (name <> ''),
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
                note TEXT
            )
        """)

    # -------------------------
    # Schedule Entries (single unified schedule table)
    # Works for CH and HW
    # -------------------------
    if not _table_exists(cur, "schedule_entries"):
        print("[DB_INIT] Creating schedule_entries")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schedule_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_set_name TEXT NOT NULL,
                system TEXT NOT NULL CHECK (system IN ('CH','HW')),   -- 'CH' or 'HW'
                days TEXT NOT NULL,                                   -- '0123456'
                start_time TEXT NOT NULL,                             -- 'HH:MM'
                end_time TEXT NOT NULL,                               -- 'HH:MM'
                setpoint REAL,                                        -- NULL allowed (HW)
                warmup INTEGER NOT NULL DEFAULT 0 CHECK (warmup IN (0,1)),
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
                note TEXT,
                FOREIGN KEY(schedule_set_name) REFERENCES schedule_sets(name)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_entries_lookup ON schedule_entries(schedule_set_name, system, enabled)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_entries_days ON schedule_entries(days)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_entries_times ON schedule_entries(start_time, end_time)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_entries_set_system_start ON schedule_entries(schedule_set_name, system, start_time)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_entries_system_enabled ON schedule_entries(system, enabled)")

    conn.commit()

def seed_default_schedule_sets(conn, seed_normal_entries=True):
    """
    Creates schedule set names and (optionally) inserts baseline schedule entries.

    - NORMAL: your usual schedule
    - CHRISTMAS: placeholder, so the system can refer to it even if empty

    If seed_normal_entries=False, you'll only create the set names.
    """
    cur = conn.cursor()

    # Ensure NORMAL and CHRISTMAS exist
    sets = [
        ("NORMAL", "Default weekly schedule"),
        ("CHRISTMAS", "Placeholder special schedule (edit later)"),
        ("HOLIDAY", "Generic holiday special schedule")
    ]
    for name, note in sets:
        cur.execute("SELECT name FROM schedule_sets WHERE name=?", (name,))
        if cur.fetchone() is None:
            print("[DB_INIT] Seeding schedule set:", name)
            cur.execute(
                "INSERT INTO schedule_sets (name, enabled, note) VALUES (?, ?, ?)",
                (name, 1, note)
            )

    # Optionally seed NORMAL schedule entries if none exist yet
    if seed_normal_entries:
        cur.execute("SELECT COUNT(*) FROM schedule_entries WHERE schedule_set_name='NORMAL'")
        count = cur.fetchone()[0]
        if count == 0:
            print("[DB_INIT] Seeding placeholder NORMAL schedule entries")

            # CH defaults (same spirit as your legacy defaults)
            cur.execute("""
                INSERT INTO schedule_entries
                (schedule_set_name, system, days, start_time, end_time, setpoint, warmup, enabled, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("NORMAL", "CH", "0123456", "07:00", "08:30", 20.0, 1, 1, "Default CH morning"))

            cur.execute("""
                INSERT INTO schedule_entries
                (schedule_set_name, system, days, start_time, end_time, setpoint, warmup, enabled, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("NORMAL", "CH", "0123456", "16:30", "21:00", 20.0, 0, 1, "Default CH evening"))

            # HW defaults
            cur.execute("""
                INSERT INTO schedule_entries
                (schedule_set_name, system, days, start_time, end_time, setpoint, warmup, enabled, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("NORMAL", "HW", "0123456", "06:00", "08:00", None, 0, 1, "Default HW morning"))

            cur.execute("""
                INSERT INTO schedule_entries
                (schedule_set_name, system, days, start_time, end_time, setpoint, warmup, enabled, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("NORMAL", "HW", "0123456", "16:30", "18:00", None, 0, 1, "Default HW evening"))

    conn.commit()

def validate_setting(key, value, schema):
    try:
        setting_type = schema["type"]

        if setting_type == "int":
            val = int(value)
            if "min" in schema and val < schema["min"]:
                return False
            if "max" in schema and val > schema["max"]:
                return False
            return True

        elif setting_type == "float":
            val = float(value)
            if "min" in schema and val < schema["min"]:
                return False
            if "max" in schema and val > schema["max"]:
                return False
            return True

        elif setting_type == "str":
            if not isinstance(value, (str,)):
                # py2 unicode handling
                try:
                    value = str(value)
                except Exception:
                    return False
            if "max_len" in schema and len(value) > int(schema["max_len"]):
                return False
            return True

        elif setting_type == "bool":
            return value in ["True", "False"]

        elif setting_type == "enum":
            return value in schema["allowed"]

        elif setting_type == "time":
            time.strptime(value, "%H:%M")
            return True

    except:
        return False

    return False


def initialise_database(db_path):

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Pragmas (good defaults)
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")

    # ---- Create Tables ----

    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS schema_info
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       CHECK
                   (
                       id=
                       1
                   ),
                       version INTEGER
                       )
                   """)
    cursor.execute("SELECT version FROM schema_info WHERE id=1")
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT INTO schema_info (id, version) VALUES (1, ?)", (SCHEMA_VERSION,))
    else:
        db_version = row[0]
        if db_version < SCHEMA_VERSION:
            print("[DB_INIT] Upgrading schema...")
            # future upgrade steps here
            cursor.execute("UPDATE schema_info SET version = ?", (SCHEMA_VERSION,))

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS temperature_log (
            ts_epoch REAL,
            ts TEXT,
            source TEXT,
            value REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS state_log (
            ts_epoch REAL,
            ts TEXT,
            system TEXT,
            state TEXT
        )
    """)


    # ---- Validates and corrects settings ----

    print("[DB_INIT] Validating settings...")

    for key, schema in SETTINGS_SCHEMA.items():

        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()

        if row is None:
            print("[DB_INIT] Missing setting %s - inserting default" % key)
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (key, schema["default"])
            )
        else:
            current_value = row[0]

            if not validate_setting(key, current_value, schema):
                print("[DB_INIT] Invalid value for %s - resetting to default" % key)
                cursor.execute(
                    "UPDATE settings SET value = ? WHERE key = ?",
                    (schema["default"], key)
                )

                cursor.execute("""
                               INSERT INTO state_log (ts_epoch, ts, system, state)
                               VALUES (?, ?, ?, ?)
                               """, (
                                   time.time(),
                                   time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                                   "SYSTEM",
                                   "Corrected invalid setting %s" % key
                               ))

    # Create away/special + schedules schema
    ensure_overrides_and_schedules(conn)

    # Seed NORMAL and CHRISTMAS schedule sets (and optional NORMAL entries)
    seed_default_schedule_sets(conn, seed_normal_entries=True)

    conn.commit()
    conn.close()

    print("[DB_INIT] Database ready at:", db_path)