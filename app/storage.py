from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ArtifactRecord


class RunDatabase:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.connection = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS stage_metrics (
                stage_name TEXT NOT NULL,
                captured_at_utc TEXT NOT NULL,
                metrics_json TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS stage_artifacts (
                stage_name TEXT NOT NULL,
                captured_at_utc TEXT NOT NULL,
                artifact_name TEXT NOT NULL,
                artifact_path TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def record_stage_metrics(self, stage_name: str, metrics: dict[str, Any]) -> None:
        captured_at = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            "INSERT INTO stage_metrics VALUES (?, ?, ?)",
            (stage_name, captured_at, json.dumps(metrics, sort_keys=True)),
        )
        self.connection.commit()

    def record_stage_artifacts(self, stage_name: str, artifacts: list[ArtifactRecord]) -> None:
        captured_at = datetime.now(timezone.utc).isoformat()
        cursor = self.connection.cursor()
        for artifact in artifacts:
            cursor.execute(
                "INSERT INTO stage_artifacts VALUES (?, ?, ?, ?)",
                (stage_name, captured_at, artifact.name, artifact.path),
            )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
