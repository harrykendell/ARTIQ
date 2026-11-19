"""SQLite-WAL authoritative temperature log and versioned channel configuration."""
from __future__ import annotations

import math
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

THERMOCOUPLE_TYPES = frozenset("BEJKNRST")
RETENTION_SECONDS = 7 * 24 * 3600
MAX_HISTORY_POINTS = 600
MAX_HISTORY_SPAN = RETENTION_SECONDS


def validate_channel(value):
    if type(value) is not int or not 1 <= value <= 8:
        raise ValueError("Physical channel must be an integer from 1 to 8")
    return value


def validate_configuration(value):
    if not isinstance(value, dict) or set(value) != {
        "channel", "name", "type", "enabled", "record_with_experiments",
    }:
        raise ValueError("Expected full channel configuration")
    ch = validate_channel(value["channel"])
    name = value["name"]
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= 64) or any(
        ord(char) < 32 for char in name
    ):
        raise ValueError("Channel name must be 1-64 printable characters")
    if not isinstance(value["type"], str) or value["type"] not in THERMOCOUPLE_TYPES:
        raise ValueError("Unsupported thermocouple type")
    if type(value["enabled"]) is not bool or type(value["record_with_experiments"]) is not bool:
        raise ValueError("Flags must be boolean")
    if value["record_with_experiments"] and not value["enabled"]:
        raise ValueError("Only acquired channels can be recorded with experiments")
    return {
        "channel": ch,
        "name": name.strip(),
        "type": value["type"],
        "enabled": value["enabled"],
        "record_with_experiments": value["record_with_experiments"],
    }


def finite_or_none(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


class TemperatureStore:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS channels (
                    channel INTEGER PRIMARY KEY CHECK(channel BETWEEN 1 AND 8),
                    name TEXT NOT NULL, type TEXT NOT NULL,
                    enabled INTEGER NOT NULL, record_with_experiments INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    channel INTEGER NOT NULL CHECK(channel BETWEEN 1 AND 8),
                    value_c REAL,
                    status TEXT NOT NULL,
                    cjc_c REAL,
                    revision INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS readings_channel_time
                    ON readings(channel, timestamp);
                CREATE INDEX IF NOT EXISTS readings_time ON readings(timestamp);
                INSERT OR IGNORE INTO metadata(key, value) VALUES ('revision', '0');
            """)
            for ch in range(1, 9):
                db.execute("""
                    INSERT OR IGNORE INTO channels
                        (channel, name, type, enabled, record_with_experiments)
                    VALUES (?, ?, 'K', 0, 0)
                """, (ch, f"Channel {ch}"))

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=3)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=3000")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def config(self):
        with self._connection() as db:
            # Revision and channel rows must be from the same SQLite snapshot.
            db.execute("BEGIN")
            revision = int(db.execute(
                "SELECT value FROM metadata WHERE key='revision'").fetchone()[0])
            rows = db.execute("SELECT * FROM channels ORDER BY channel").fetchall()
        return {"available": True, "revision": revision, "channels": [{
            "channel": row["channel"], "name": row["name"], "type": row["type"],
            "enabled": bool(row["enabled"]),
            "record_with_experiments": bool(row["record_with_experiments"]),
        } for row in rows]}

    def update_channel(self, raw, expected_revision):
        config = validate_configuration(raw)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Expected revision must be a nonnegative integer")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            revision = int(db.execute(
                "SELECT value FROM metadata WHERE key='revision'").fetchone()[0])
            if revision != expected_revision:
                raise ValueError("Configuration changed; reload before saving")
            db.execute("""
                UPDATE channels SET name=?, type=?, enabled=?, record_with_experiments=?
                WHERE channel=?
            """, (config["name"], config["type"], int(config["enabled"]),
                  int(config["record_with_experiments"]), config["channel"]))
            db.execute("UPDATE metadata SET value=? WHERE key='revision'",
                       (str(revision + 1),))
        return self.config()

    def append(self, timestamp, config, readings, cjc_c):
        """Insert status records for every enabled physical channel at one instant."""
        timestamp = float(timestamp)
        with self._connection() as db:
            db.executemany("""
                INSERT INTO readings
                    (timestamp, channel, value_c, status, cjc_c, revision, name, type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (timestamp, entry["channel"],
                 finite_or_none(readings.get(entry["channel"], {}).get("value_c")),
                 str(readings.get(entry["channel"], {}).get("status", "missing"))[:40],
                 finite_or_none(cjc_c), config["revision"],
                 entry["name"], entry["type"])
                for entry in config["channels"] if entry["enabled"]
            ])

    def nearest(self, timestamp, channels=None):
        timestamp = float(timestamp)
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("Invalid UTC timestamp")
        channels = list(range(1, 9)) if channels is None else channels
        result = {}
        with self._connection() as db:
            for ch in channels:
                validate_channel(ch)
                before = db.execute("""
                    SELECT * FROM readings WHERE channel=? AND timestamp<=?
                    ORDER BY timestamp DESC LIMIT 1
                """, (ch, timestamp)).fetchone()
                after = db.execute("""
                    SELECT * FROM readings WHERE channel=? AND timestamp>=?
                    ORDER BY timestamp ASC LIMIT 1
                """, (ch, timestamp)).fetchone()
                record = min((record for record in (before, after) if record is not None),
                             key=lambda row: abs(row["timestamp"] - timestamp), default=None)
                if record is not None:
                    result[str(ch)] = {
                        "channel": ch, "timestamp": record["timestamp"],
                        "value_c": record["value_c"], "status": record["status"],
                        "valid": record["status"] == "ok" and record["value_c"] is not None,
                        "revision": record["revision"],
                        "name": record["name"], "type": record["type"],
                    }
        return result

    def history(self, start, end, channels, max_points=600):
        start, end = float(start), float(end)
        if (not math.isfinite(start) or not math.isfinite(end) or start < 0 or
                end <= start or end - start > MAX_HISTORY_SPAN):
            raise ValueError("History range must be <= 7 days")
        if (not isinstance(channels, list) or not 1 <= len(channels) <= 8 or
                any(type(ch) is not int or not 1 <= ch <= 8 for ch in channels) or
                len(set(channels)) != len(channels)):
            raise ValueError("Choose 1-8 distinct channels")
        if type(max_points) is not int or not 20 <= max_points <= MAX_HISTORY_POINTS:
            raise ValueError("max_points must be 20..600")
        # One bucket retains first, last, minimum and maximum plus first
        # invalid marker. Streaming aggregation bounds memory independently
        # of 7-day raw sample count; raw SQLite rows are never loaded into RAM.
        bucket_count = max(1, max_points // (5 * len(channels)))
        width = (end - start) / bucket_count
        output = []
        with self._connection() as db:
            for ch in sorted(channels):
                cursor = db.execute("""
                    SELECT timestamp, channel, value_c, status, cjc_c, revision,
                           name, type FROM readings
                    WHERE channel=? AND timestamp>=? AND timestamp<=?
                    ORDER BY timestamp ASC
                """, (ch, start, end))
                current_bucket = None
                candidates = {}
                previous = None
                segment = 0
                def flush():
                    if candidates:
                        unique = {row["timestamp"]: row for row in candidates.values()}
                        output.extend(sorted(unique.values(), key=lambda row: row["timestamp"]))
                for raw_row in cursor:
                    row = dict(raw_row)
                    if previous is not None and (
                            row["timestamp"] - previous["timestamp"] > 20 or
                            previous["status"] != "ok" or previous["value_c"] is None):
                        segment += 1
                    row["segment"] = segment
                    if row["status"] != "ok" or row["value_c"] is None:
                        segment += 1
                    previous = row
                    bucket = min(bucket_count - 1, int((row["timestamp"] - start) / width))
                    if bucket != current_bucket:
                        flush()
                        candidates = {}
                        current_bucket = bucket
                    candidates.setdefault("first", row)
                    candidates["last"] = row
                    if row["status"] != "ok" or row["value_c"] is None:
                        candidates.setdefault("invalid", row)
                    else:
                        if ("min" not in candidates or
                                row["value_c"] < candidates["min"]["value_c"]):
                            candidates["min"] = row
                        if ("max" not in candidates or
                                row["value_c"] > candidates["max"]["value_c"]):
                            candidates["max"] = row
                flush()
        output.sort(key=lambda row: (row["timestamp"], row["channel"]))
        return {
            "start": start, "end": end,
            "rows": [
                [row["timestamp"], row["channel"], row["value_c"], row["status"],
                 row["cjc_c"], row["revision"], row["name"], row["type"],
                 row["segment"]]
                for row in output
            ],
        }

    def prune(self, now=None):
        cutoff = (time.time() if now is None else now) - RETENTION_SECONDS
        with self._connection() as db:
            removed = db.execute("DELETE FROM readings WHERE timestamp < ?", (cutoff,)).rowcount
        return removed
