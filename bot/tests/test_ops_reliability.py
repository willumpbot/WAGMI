"""
Tests for Push 2 — Ops Reliability Hardening:
  - MigrationRunner: table creation, skip-applied, run-new
  - AlertRouter state persistence: save/load cycle, prune old entries
"""

import json
import os
import sqlite3
import sys
import tempfile
import time

import pytest

# Ensure bot/ is on the import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.migrations import MigrationRunner


# ── MigrationRunner Tests ───────────────────────────────────────


class TestMigrationRunner:

    def _make_conn(self) -> sqlite3.Connection:
        """Create an in-memory SQLite connection."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return conn

    def test_migration_runner_creates_table(self):
        """MigrationRunner.__init__ creates the _migrations tracking table."""
        conn = self._make_conn()
        MigrationRunner(conn)

        # The table should exist
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='_migrations'"
        ).fetchone()
        assert row is not None, "_migrations table was not created"

        # Verify schema has expected columns
        columns = conn.execute("PRAGMA table_info(_migrations)").fetchall()
        col_names = {c["name"] for c in columns}
        assert "version" in col_names
        assert "description" in col_names
        assert "applied_at" in col_names

        conn.close()

    def test_migration_runner_skips_applied(self):
        """Running migrations twice does not create duplicate entries."""
        conn = self._make_conn()
        runner = MigrationRunner(conn)

        migrations = [
            (1, "baseline", "SELECT 1"),
            (2, "add column", "SELECT 1"),
        ]

        # First run
        count1 = runner.run_pending(migrations)
        assert count1 == 2

        # Second run — should skip all
        count2 = runner.run_pending(migrations)
        assert count2 == 0

        # Verify exactly 2 entries in the tracking table
        rows = conn.execute("SELECT * FROM _migrations").fetchall()
        assert len(rows) == 2

        conn.close()

    def test_migration_runner_runs_new(self):
        """Adding a new migration to the list causes only the new one to run."""
        conn = self._make_conn()
        runner = MigrationRunner(conn)

        # Run version 1 only
        migrations_v1 = [(1, "baseline", "SELECT 1")]
        count1 = runner.run_pending(migrations_v1)
        assert count1 == 1

        # Now add version 2 — a real CREATE TABLE
        migrations_v2 = [
            (1, "baseline", "SELECT 1"),
            (2, "add test table", "CREATE TABLE IF NOT EXISTS test_v2 (id INTEGER PRIMARY KEY, name TEXT)"),
        ]
        count2 = runner.run_pending(migrations_v2)
        assert count2 == 1

        # Verify the table was created by migration v2
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_v2'"
        ).fetchone()
        assert row is not None, "Migration v2 did not create the test_v2 table"

        # Verify both versions are recorded
        rows = conn.execute(
            "SELECT version FROM _migrations ORDER BY version"
        ).fetchall()
        versions = [r["version"] for r in rows]
        assert versions == [1, 2]

        conn.close()

    def test_migration_runner_callable_step(self):
        """Callable migration steps receive the connection and execute."""
        conn = self._make_conn()
        runner = MigrationRunner(conn)

        call_log = []

        def my_migration(c: sqlite3.Connection):
            c.execute("CREATE TABLE callable_test (val TEXT)")
            call_log.append("executed")

        migrations = [
            (1, "baseline", "SELECT 1"),
            (2, "callable migration", my_migration),
        ]

        count = runner.run_pending(migrations)
        assert count == 2
        assert call_log == ["executed"]

        # Verify the table exists
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='callable_test'"
        ).fetchone()
        assert row is not None

        conn.close()

    def test_migration_runner_duplicate_column_safe(self):
        """ALTER TABLE with duplicate column is silently ignored."""
        conn = self._make_conn()
        conn.execute("CREATE TABLE dup_test (id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()

        runner = MigrationRunner(conn)

        migrations = [
            (1, "add name column (already exists)",
             "ALTER TABLE dup_test ADD COLUMN name TEXT"),
        ]

        # Should not raise — duplicate column is caught
        count = runner.run_pending(migrations)
        assert count == 1

        conn.close()


# ── Alert State Persistence Tests ──────────────────────────────


class TestAlertStatePersistence:

    def test_alert_state_persistence(self):
        """AlertRouter save/load cycle preserves recent rate-limit state."""
        # We test the _save_state / _load_state methods directly by
        # manipulating the state path to use a temp directory.
        from alerts.router import AlertRouter

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "alert_state.json")

            # Create router and inject state path
            router = AlertRouter()
            router._state_path = state_path

            # Populate state
            now = int(time.time())
            router._last_sent["BTC/USDT"] = {
                "prio_ts": now - 30,
                "reg_ts": now - 10,
                "fingerprint": "BTC/USDT:long:PRIORITY:80",
            }
            router._save_state()

            # Verify file was written
            assert os.path.exists(state_path)

            # Create a new router that loads from the same file
            router2 = AlertRouter()
            router2._state_path = state_path
            router2._load_state()

            # Verify state was restored
            assert "BTC/USDT" in router2._last_sent
            entry = router2._last_sent["BTC/USDT"]
            assert entry["prio_ts"] == now - 30
            assert entry["reg_ts"] == now - 10
            assert entry["fingerprint"] == "BTC/USDT:long:PRIORITY:80"

    def test_alert_state_prunes_old(self):
        """Entries older than 600 seconds are NOT loaded from disk."""
        from alerts.router import AlertRouter

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "alert_state.json")

            now = int(time.time())
            old_ts = now - 700  # > 600 seconds ago
            recent_ts = now - 100  # < 600 seconds ago

            # Write state file with one old and one recent entry
            data = {
                "last_sent": {
                    "OLD/USDT": {
                        "prio_ts": old_ts,
                        "reg_ts": old_ts,
                        "fingerprint": "old",
                    },
                    "NEW/USDT": {
                        "prio_ts": recent_ts,
                        "reg_ts": recent_ts,
                        "fingerprint": "new",
                    },
                },
                "prio_burst": {
                    "OLD/USDT": [old_ts],
                    "NEW/USDT": [recent_ts],
                },
            }
            with open(state_path, "w") as f:
                json.dump(data, f)

            # Load state
            router = AlertRouter()
            router._state_path = state_path
            router._load_state()

            # Recent entry should be restored
            assert "NEW/USDT" in router._last_sent
            assert router._last_sent["NEW/USDT"]["fingerprint"] == "new"

            # Old entry should be pruned
            assert "OLD/USDT" not in router._last_sent

            # Burst: old entries pruned, recent kept
            assert "NEW/USDT" in router._prio_burst
            assert len(router._prio_burst["NEW/USDT"]) == 1
            # OLD/USDT burst should be empty or absent
            assert len(router._prio_burst.get("OLD/USDT", [])) == 0

    def test_alert_state_handles_missing_file(self):
        """_load_state gracefully handles a nonexistent file."""
        from alerts.router import AlertRouter

        router = AlertRouter()
        router._state_path = "/nonexistent/path/alert_state.json"
        # Should not raise
        router._load_state()
        # State should remain at defaults
        assert len(router._last_sent) == 0

    def test_alert_state_handles_corrupt_file(self):
        """_load_state gracefully handles a corrupt JSON file."""
        from alerts.router import AlertRouter

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "alert_state.json")
            with open(state_path, "w") as f:
                f.write("{corrupted json !!!")

            router = AlertRouter()
            router._state_path = state_path
            # Should not raise
            router._load_state()
            assert len(router._last_sent) == 0
