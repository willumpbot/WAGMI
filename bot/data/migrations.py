"""
SQLite migration system for the bot database.

Tracks applied migrations in a `_migrations` table and runs pending ones
in order.  Each migration is a (version, description, sql_or_callable)
tuple.  SQL strings are executed directly; callables receive the
connection object.

Safe ALTER TABLE handling: duplicate-column errors are caught and
silently ignored so that migrations are idempotent.

Usage:
    from data.migrations import MigrationRunner
    conn = sqlite3.connect("bot.db")
    MigrationRunner(conn).run_pending()
"""

import logging
import sqlite3
from typing import Callable, List, Tuple, Union

logger = logging.getLogger("bot.migrations")

# Type alias: a migration step is SQL text or a callable(conn).
MigrationStep = Union[str, Callable[[sqlite3.Connection], None]]

# ---------------------------------------------------------------------------
# Migration registry
# ---------------------------------------------------------------------------
# Add new migrations here as tuples: (version, description, sql_or_callable)
# Version numbers must be unique and monotonically increasing.
#
#   Version 1 = baseline (no-op), confirms migration system is working.
#   Future versions add columns, tables, indexes, etc.
# ---------------------------------------------------------------------------

MIGRATIONS: List[Tuple[int, str, MigrationStep]] = [
    (1, "baseline — migration system initialized", "SELECT 1"),
]


class MigrationRunner:
    """Run numbered database migrations, tracking state in `_migrations`."""

    TRACKING_TABLE = "_migrations"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._ensure_tracking_table()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_tracking_table(self) -> None:
        """Create the tracking table if it does not exist."""
        self.conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.TRACKING_TABLE} (
                version  INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        self.conn.commit()

    def _current_version(self) -> int:
        """Return the highest applied migration version, or 0 if none."""
        row = self.conn.execute(
            f"SELECT MAX(version) FROM {self.TRACKING_TABLE}"
        ).fetchone()
        return row[0] if row and row[0] is not None else 0

    def _is_applied(self, version: int) -> bool:
        """Check whether a specific version has already been applied."""
        row = self.conn.execute(
            f"SELECT 1 FROM {self.TRACKING_TABLE} WHERE version = ?",
            (version,),
        ).fetchone()
        return row is not None

    def _record(self, version: int, description: str) -> None:
        """Mark a migration as applied."""
        self.conn.execute(
            f"INSERT INTO {self.TRACKING_TABLE} (version, description) VALUES (?, ?)",
            (version, description),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_pending(self, migrations: List[Tuple[int, str, MigrationStep]] = None) -> int:
        """Run all migrations whose version exceeds the current DB version.

        Args:
            migrations: Optional override list; defaults to the module-level
                        MIGRATIONS registry.

        Returns:
            Number of migrations applied in this call.
        """
        if migrations is None:
            migrations = MIGRATIONS

        applied_count = 0

        for version, description, step in sorted(migrations, key=lambda m: m[0]):
            if self._is_applied(version):
                continue

            logger.info(
                "Running migration v%d: %s", version, description
            )

            try:
                if callable(step):
                    step(self.conn)
                else:
                    # Execute raw SQL, handling safe ALTER TABLE errors
                    self._safe_execute(step)

                self._record(version, description)
                applied_count += 1
                logger.info("Migration v%d applied successfully", version)

            except Exception as exc:
                logger.error(
                    "Migration v%d failed: %s", version, exc
                )
                raise

        if applied_count:
            logger.info(
                "Migrations complete: %d applied, DB now at v%d",
                applied_count,
                self._current_version(),
            )
        else:
            logger.debug(
                "No pending migrations (DB at v%d)",
                self._current_version(),
            )

        return applied_count

    def _safe_execute(self, sql: str) -> None:
        """Execute SQL, silently ignoring duplicate-column errors.

        SQLite raises an OperationalError with 'duplicate column name'
        when ALTER TABLE ADD COLUMN hits an existing column.  We catch
        that specific case so migrations are idempotent.
        """
        try:
            self.conn.executescript(sql)
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "duplicate column" in msg:
                logger.info(
                    "Ignored duplicate-column error (idempotent): %s", exc
                )
            else:
                raise
