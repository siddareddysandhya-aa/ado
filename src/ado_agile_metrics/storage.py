"""SQLite persistence for dashboard selections and metric snapshots."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class SnapshotStore:
    """Small SQLite repository for saved dashboards and historical KPIs."""

    LAST_USED_NAME = "__last_used__"

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_path, check_same_thread=False)
        self.connection.execute("CREATE TABLE IF NOT EXISTS dashboards (name TEXT PRIMARY KEY, config TEXT NOT NULL, created_at TEXT NOT NULL)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS snapshots (captured_at TEXT NOT NULL, project TEXT NOT NULL, metrics TEXT NOT NULL)")
        self.connection.commit()

    def save_dashboard(self, name: str, config: dict[str, object]) -> None:
        """Create or replace a named dashboard configuration."""
        self.connection.execute("INSERT OR REPLACE INTO dashboards VALUES (?, ?, ?)", (name, json.dumps(config), datetime.now(timezone.utc).isoformat()))
        self.connection.commit()

    def dashboard_names(self) -> list[str]:
        """Return saved dashboard names."""
        return [row[0] for row in self.connection.execute("SELECT name FROM dashboards WHERE name != ? ORDER BY name", (self.LAST_USED_NAME,))]

    def load_dashboard(self, name: str) -> dict[str, object]:
        """Return the saved filter and metric configuration for a named dashboard."""
        row = self.connection.execute("SELECT config FROM dashboards WHERE name = ?", (name,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_last_used(self, config: dict[str, object]) -> None:
        """Persist the current filter selection for automatic restoration next session."""
        self.save_dashboard(self.LAST_USED_NAME, config)

    def load_last_used(self) -> dict[str, object]:
        """Return the most recently used dashboard filter selection."""
        return self.load_dashboard(self.LAST_USED_NAME)

    def snapshot(self, project: str, metrics: dict[str, float]) -> None:
        """Persist a timestamped KPI snapshot for longitudinal analysis."""
        self.connection.execute("INSERT INTO snapshots VALUES (?, ?, ?)", (datetime.now(timezone.utc).isoformat(), project, json.dumps(metrics)))
        self.connection.commit()