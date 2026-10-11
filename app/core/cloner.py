import os
import shutil
import re
from typing import Optional
from git import Repo, GitCommandError
from pydantic import BaseModel, ValidationError
from app.models.schemas import ScanResult

class Cloner:
    def __init__(self, base_dir: str = "repositories"):
        self.base_dir = base_dir
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)

    def validate_url(self, url: str) -> bool:
        # Pattern for https://github.com/owner/repo
        pattern = r"^https://github\.com/[\w\.-]+/[\w\.-]+/?$"
        return bool(re.match(pattern, url))

    def clone_repository(self, url: str, token: Optional[str] = None) -> str:
        if not self.validate_url(url):
            raise ValueError(f"Invalid GitHub URL: {url}")

        repo_name = url.split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        target_dir = os.path.join(self.base_dir, repo_name)

        # Cleanup existing if any
        if os.path.exists(target_dir):
            self.cleanup(target_dir)

        try:
            clone_url = url
            if token:
                # Handle token for HTTPS auth
                # Format: https://<token>@github.com/owner/repo
                clone_url = url.replace("https://", f"https://{token}@")

            Repo.clone_from(clone_url, target_dir, depth=1)
            return target_dir
        except GitCommandError as e:
            raise RuntimeError(f"Git clone failed: {e}")

    def get_commit_sha(self, repo_path: str) -> str:
        try:
            repo = Repo(repo_path)
            sha = repo.head.commit.hexsha
            # Explicitly close the repo to release file handles on Windows
            repo.close()
            return sha
        except Exception as e:
            return f"Unknown ({e})"

    def cleanup(self, repo_path: str):
        if os.path.exists(repo_path):
            def remove_readonly(func, path, excinfo):
                import stat
                os.chmod(path, stat.S_IWRITE)
                func(path)

            shutil.rmtree(repo_path, onerror=remove_readonly)
