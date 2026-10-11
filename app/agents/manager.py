import logging
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from app.core.cloner import Cloner
from app.core.db import SQLiteStore
from app.models.analysis import PipelineOutcome
from app.pipeline import AnalysisPipeline

logger = logging.getLogger(__name__)


class AnalysisManager:
    """Thread-backed run manager with commit-SHA cache reuse."""

    def __init__(
        self,
        store: SQLiteStore | None = None,
        pipeline: AnalysisPipeline | None = None,
        cloner: Cloner | None = None,
        github_token: str | None = None,
    ):
        self.store = store or SQLiteStore()
        self.pipeline = pipeline or AnalysisPipeline()
        self.cloner = cloner or self.pipeline.cloner
        self.github_token = github_token if github_token is not None else os.getenv("GITHUB_TOKEN") or None
        self._threads: dict[str, threading.Thread] = {}
        self._execution_lock = threading.Lock()

    def start(self, repository_url: str) -> str:
        if not self.cloner.validate_url(repository_url):
            raise ValueError("URL must be https://github.com/<owner>/<repo>.")

        run_id = str(uuid.uuid4())
        self.store.create_run(run_id, repository_url)
        thread = threading.Thread(
            target=self._execute,
            args=(run_id, repository_url),
            name=f"repoinsight-{run_id[:8]}",
            daemon=True,
        )
        self._threads[run_id] = thread
        thread.start()
        return run_id

    def _execute(self, run_id: str, repository_url: str) -> None:
        with self._execution_lock:
            self._execute_locked(run_id, repository_url)

    def _execute_locked(self, run_id: str, repository_url: str) -> None:
        repo_path: str | None = None
        cleanup_required = False
        try:
            self.store.update_progress(run_id, "Cloning repository...")
            repo_path = self.cloner.clone_repository(
                repository_url, token=self.github_token
            )
            cleanup_required = True
            commit_sha = self.cloner.get_commit_sha(repo_path)
            if not commit_sha or commit_sha.startswith("Unknown"):
                raise RuntimeError("Could not determine repository commit SHA.")

            cached = self.store.find_cached(repository_url, commit_sha)
            if cached:
                self.store.update_progress(run_id, "Reusing cached analysis...")
                self.store.complete_run(
                    run_id,
                    commit_sha,
                    cached["analysis"],
                    cached["outputs"],
                )
                return

            outcome: PipelineOutcome = self.pipeline.run(
                repository_url,
                progress=lambda message: self.store.update_progress(
                    run_id, message
                ),
                github_token=self.github_token,
                repository_path=repo_path,
                commit_sha=commit_sha,
            )
            self.store.complete_run(
                run_id,
                outcome.commit_sha,
                outcome.analysis.model_dump(mode="json"),
                outcome.outputs,
            )
        except Exception as error:  # noqa: BLE001
            # This thread boundary must persist all pipeline failures as failed runs.
            logger.error(
                "Analysis run %s failed with %s", run_id, type(error).__name__
            )
            self.store.fail_run(run_id, self._safe_error(error))
        finally:
            if cleanup_required and repo_path:
                try:
                    self.cloner.cleanup(repo_path)
                except OSError:
                    logger.exception("Failed to clean cloned repository for run %s", run_id)
            self._threads.pop(run_id, None)

    def get_status(self, run_id: str) -> dict[str, Any] | None:
        return self.store.get_run(run_id)

    def get_results(self, run_id: str) -> dict[str, Any] | None:
        run = self.store.get_run(run_id)
        if not run:
            return None
        if run["status"] != "completed":
            return {"run": run, "analysis": None, "outputs": {}}
        return {
            "run": run,
            "analysis": self.store.get_analysis(run_id),
            "outputs": self.store.get_outputs(run_id),
        }

    def get_download(self, run_id: str, output_type: str) -> Path | None:
        if output_type not in {"pdf", "pptx", "json", "png", "svg"}:
            raise ValueError("Unsupported download type.")
        run = self.store.get_run(run_id)
        if not run:
            return None
        if run["status"] != "completed":
            raise RuntimeError("Analysis outputs are not ready.")
        output_path = self.store.get_outputs(run_id).get(output_type)
        if not output_path:
            return None
        path = Path(output_path)
        if not path.is_file():
            return None
        return path

    def _safe_error(self, error: Exception) -> str:
        message = str(error)
        if self.github_token:
            message = message.replace(self.github_token, "[REDACTED]")
        message = re.sub(
            r"(https://)[^/@\s]+@github\.com",
            r"\1[REDACTED]@github.com",
            message,
            flags=re.IGNORECASE,
        )
        if not message.strip():
            return f"{type(error).__name__}: analysis failed"
        return f"{type(error).__name__}: {message[:1000]}"
