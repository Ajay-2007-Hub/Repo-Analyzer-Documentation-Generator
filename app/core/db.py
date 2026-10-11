import json
import sqlite3
from pathlib import Path
from typing import Any, ClassVar


class SQLiteStore:
    """Persistent run state, analysis JSON, generated artifacts, and cache lookup."""

    REQUIRED_CACHED_OUTPUTS: ClassVar[set[str]] = {"pdf", "pptx", "json", "png", "svg"}

    def __init__(self, db_path: str | Path = "database/repoinsight.sqlite3"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    repository_url TEXT NOT NULL,
                    commit_sha TEXT,
                    status TEXT NOT NULL,
                    progress TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_runs_cache
                    ON runs(repository_url, commit_sha, status);
                CREATE TABLE IF NOT EXISTS analysis (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outputs (
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    output_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    PRIMARY KEY(run_id, output_type)
                );
                """
            )

    def create_run(self, run_id: str, repository_url: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (id, repository_url, status, progress)
                VALUES (?, ?, 'queued', 'Queued for analysis')
                """,
                (run_id, repository_url),
            )

    def update_progress(self, run_id: str, message: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET status = 'running', progress = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (message, run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Run not found or no longer active: {run_id}")

    def complete_run(
        self,
        run_id: str,
        commit_sha: str,
        analysis_data: dict[str, Any],
        outputs: dict[str, str],
    ) -> None:
        encoded_analysis = json.dumps(analysis_data, ensure_ascii=False)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET commit_sha = ?, status = 'completed', progress = 'Analysis complete',
                    error = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (commit_sha, run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Run not found or no longer active: {run_id}")
            connection.execute(
                "INSERT OR REPLACE INTO analysis (run_id, data_json) VALUES (?, ?)",
                (run_id, encoded_analysis),
            )
            connection.execute("DELETE FROM outputs WHERE run_id = ?", (run_id,))
            connection.executemany(
                "INSERT INTO outputs (run_id, output_type, path) VALUES (?, ?, ?)",
                [
                    (run_id, output_type, str(path))
                    for output_type, path in outputs.items()
                ],
            )

    def fail_run(self, run_id: str, error: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET status = 'failed', progress = 'Analysis failed', error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (error, run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Run not found or no longer active: {run_id}")

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, repository_url, commit_sha, status, progress, error,
                       created_at, updated_at
                FROM runs WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_analysis(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data_json FROM analysis WHERE run_id = ?", (run_id,)
            ).fetchone()
        return json.loads(row["data_json"]) if row else None

    def get_outputs(self, run_id: str) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT output_type, path FROM outputs WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        return {row["output_type"]: row["path"] for row in rows}

    def find_cached(
        self, repository_url: str, commit_sha: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT r.id, a.data_json
                FROM runs AS r
                JOIN analysis AS a ON a.run_id = r.id
                WHERE r.repository_url = ? AND r.commit_sha = ?
                  AND r.status = 'completed'
                ORDER BY r.updated_at DESC
                LIMIT 1
                """,
                (repository_url, commit_sha),
            ).fetchone()
            if row is None:
                return None
            rows = connection.execute(
                "SELECT output_type, path FROM outputs WHERE run_id = ?",
                (row["id"],),
            ).fetchall()

        outputs = {item["output_type"]: item["path"] for item in rows}
        if not self.REQUIRED_CACHED_OUTPUTS.issubset(outputs):
            return None
        if not all(Path(path).is_file() for path in outputs.values()):
            return None
        return {
            "run_id": row["id"],
            "analysis": json.loads(row["data_json"]),
            "outputs": outputs,
        }
