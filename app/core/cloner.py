import logging
import os
import re
import shutil
import stat
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, Repo

logger = logging.getLogger(__name__)


class Cloner:
    def __init__(self, base_dir: str = "repositories"):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def validate_url(self, url: str) -> bool:
        if not isinstance(url, str):
            return False
        match = re.fullmatch(
            r"https://github\.com/([\w.-]+)/([\w.-]+)(?:\.git)?/?",
            url,
            flags=re.IGNORECASE,
        )
        return bool(
            match
            and match.group(1) not in {".", ".."}
            and match.group(2) not in {".", ".."}
        )

    def clone_repository(self, url: str, token: str | None = None) -> str:
        if not self.validate_url(url):
            raise ValueError("URL must be https://github.com/<owner>/<repo>.")

        owner, repo_name = url.rstrip("/").split("/")[-2:]
        if repo_name.lower().endswith(".git"):
            repo_name = repo_name[:-4]

        target_dir = (self.base_dir / owner / repo_name).resolve()
        self._validate_managed_path(target_dir)
        if target_dir.exists():
            self.cleanup(str(target_dir))
        target_dir.parent.mkdir(parents=True, exist_ok=True)

        clone_url = url
        if token:
            clone_url = url.replace("https://", f"https://{token}@", 1)
        try:
            Repo.clone_from(clone_url, str(target_dir), depth=1)
            return str(target_dir)
        except GitCommandError as error:
            if target_dir.exists():
                self.cleanup(str(target_dir))
            logger.warning("Git clone failed for %s", self._safe_url(url))
            raise RuntimeError(
                "Git clone failed. Verify that the repository exists and is public, "
                "or that GITHUB_TOKEN has access."
            ) from error

    def get_commit_sha(self, repo_path: str) -> str:
        try:
            repo = Repo(repo_path)
            try:
                return repo.head.commit.hexsha
            finally:
                repo.close()
        except (InvalidGitRepositoryError, GitCommandError, OSError, ValueError):
            logger.warning("Could not determine repository commit: %s", repo_path)
            return "Unknown"

    def cleanup(self, repo_path: str) -> None:
        target = Path(repo_path).resolve()
        self._validate_managed_path(target)
        if target.exists():
            def remove_readonly(func, path, excinfo):
                os.chmod(path, stat.S_IWRITE)
                func(path)

            shutil.rmtree(target, onerror=remove_readonly)

    def _validate_managed_path(self, target: Path) -> None:
        if target == self.base_dir or not target.is_relative_to(self.base_dir):
            raise ValueError(
                "Repository path must be inside the configured repository directory."
            )

    @staticmethod
    def _safe_url(url: str) -> str:
        return re.sub(
            r"(https://)[^/@\s]+@github\.com",
            r"\1[REDACTED]@github.com",
            url,
            flags=re.IGNORECASE,
        )
