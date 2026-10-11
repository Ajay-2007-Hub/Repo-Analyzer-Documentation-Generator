import fnmatch
import logging
import os
from pathlib import Path
from typing import ClassVar

from app.models.schemas import FileInfo, ScanResult

logger = logging.getLogger(__name__)


class Scanner:
    BINARY_EXTENSIONS: ClassVar[set[str]] = {
        ".exe",
        ".dll",
        ".so",
        ".bin",
        ".pyc",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".7z",
        ".iso",
        ".ico",
    }
    MINIFIED_EXTENSIONS: ClassVar[set[str]] = {".min.js", ".min.css"}

    def __init__(
        self,
        max_files: int = 5000,
        max_file_kb: int = 500,
        max_repo_mb: int = 100,
    ):
        if max_files < 1 or max_file_kb < 1 or max_repo_mb < 1:
            raise ValueError("Scanner file and repository limits must be positive.")
        self.max_files = max_files
        self.max_file_kb = max_file_kb
        self.max_repo_mb = max_repo_mb

    def is_binary(self, file_path: str) -> bool:
        if Path(file_path).suffix.lower() in self.BINARY_EXTENSIONS:
            return True

        try:
            with open(file_path, "rb") as file_handle:
                return b"\x00" in file_handle.read(1024)
        except OSError:
            logger.warning("Could not inspect file type: %s", file_path)
            return True

    def count_lines(self, file_path: str) -> int:
        try:
            with open(file_path, "rb") as file_handle:
                return sum(1 for _ in file_handle)
        except OSError:
            logger.warning("Could not count file lines: %s", file_path)
            return 0

    def scan(self, repo_path: str, repo_name: str, commit_sha: str) -> ScanResult:
        root_path = Path(repo_path).resolve()
        files_info: list[FileInfo] = []
        total_lines = 0
        total_size_bytes = 0
        tree: dict = {}
        ignore_rules: list[tuple[str, str, bool, bool]] = []
        max_repo_bytes = self.max_repo_mb * 1024 * 1024
        stop_scanning = False

        for root, dirs, files in os.walk(root_path, followlinks=False):
            current_dir = Path(root)
            relative_dir = current_dir.relative_to(root_path).as_posix()
            if relative_dir == ".":
                relative_dir = ""

            self._load_gitignore(current_dir, relative_dir, ignore_rules)

            safe_dirs = []
            for directory in sorted(dirs):
                if directory == ".git":
                    continue
                directory_path = current_dir / directory
                relative_path = self._relative_path(directory_path, root_path)
                try:
                    if directory_path.is_symlink() or self._is_ignored(
                        relative_path, True, ignore_rules
                    ):
                        continue
                except OSError:
                    logger.warning("Could not inspect directory: %s", relative_path)
                    continue
                safe_dirs.append(directory)
            dirs[:] = safe_dirs

            for filename in sorted(files):
                if len(files_info) >= self.max_files:
                    stop_scanning = True
                    break

                file_path = current_dir / filename
                relative_path = self._relative_path(file_path, root_path)
                if relative_path.endswith(tuple(self.MINIFIED_EXTENSIONS)):
                    continue
                try:
                    if file_path.is_symlink() or self._is_ignored(
                        relative_path, False, ignore_rules
                    ):
                        continue
                    size_bytes = file_path.stat().st_size
                except OSError:
                    logger.warning("Could not inspect file: %s", relative_path)
                    continue

                if size_bytes > self.max_file_kb * 1024:
                    continue
                if total_size_bytes + size_bytes > max_repo_bytes:
                    logger.warning(
                        "Repository scan size limit reached at %s", relative_path
                    )
                    stop_scanning = True
                    break

                binary = self.is_binary(str(file_path))
                lines = 0 if binary else self.count_lines(str(file_path))
                file_info = FileInfo(
                    path=relative_path,
                    size_kb=size_bytes / 1024,
                    lines=lines,
                    extension=file_path.suffix,
                    is_binary=binary,
                )
                files_info.append(file_info)
                total_lines += lines
                total_size_bytes += size_bytes

                tree_parts = relative_path.split("/")
                current_tree = tree
                for part in tree_parts[:-1]:
                    current_tree = current_tree.setdefault(part, {})
                current_tree[tree_parts[-1]] = "file"

            if stop_scanning:
                break

        return ScanResult(
            repository_name=repo_name,
            commit_sha=commit_sha,
            total_files=len(files_info),
            total_lines=total_lines,
            total_size_mb=total_size_bytes / (1024 * 1024),
            files=files_info,
            file_tree=tree,
        )

    def _load_gitignore(
        self,
        directory: Path,
        relative_dir: str,
        rules: list[tuple[str, str, bool, bool]],
    ) -> None:
        ignore_file = directory / ".gitignore"
        if not ignore_file.is_file():
            return
        try:
            lines = ignore_file.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError:
            logger.warning("Could not read ignore rules: %s", ignore_file)
            return

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            negate = line.startswith("!") and not line.startswith("\\!")
            if negate:
                line = line[1:]
            line = line.replace(r"\#", "#").replace(r"\!", "!")
            if not line:
                continue
            directory_only = line.endswith("/")
            pattern = line.strip("/")
            if pattern:
                rules.append((relative_dir, pattern, negate, directory_only))

    @staticmethod
    def _relative_path(file_path: Path, root_path: Path) -> str:
        return file_path.relative_to(root_path).as_posix()

    @staticmethod
    def _is_ignored(
        relative_path: str,
        is_directory: bool,
        rules: list[tuple[str, str, bool, bool]],
    ) -> bool:
        ignored = False
        for base, pattern, negate, directory_only in rules:
            if base and relative_path != base and not relative_path.startswith(
                base + "/"
            ):
                continue
            local_path = relative_path[len(base) :].lstrip("/") if base else relative_path
            local_parts = local_path.split("/")
            matches = False
            if "/" in pattern:
                matches = fnmatch.fnmatchcase(local_path, pattern)
                if not matches and (is_directory or directory_only):
                    matches = any(
                        fnmatch.fnmatchcase(
                            "/".join(local_parts[:index]), pattern
                        )
                        for index in range(1, len(local_parts))
                    )
            else:
                matches = any(
                    fnmatch.fnmatchcase(part, pattern)
                    for part in local_parts
                )
            if directory_only and not is_directory and not matches:
                matches = any(
                    fnmatch.fnmatchcase(part, pattern)
                    for part in local_parts[:-1]
                )
            if matches:
                ignored = not negate
        return ignored

    def print_tree(self, tree: dict, indent: str = "") -> None:
        for key, value in tree.items():
            if isinstance(value, dict):
                print(f"{indent}📁 {key}/")
                self.print_tree(value, indent + "  ")
            else:
                print(f"{indent}📄 {key}")
