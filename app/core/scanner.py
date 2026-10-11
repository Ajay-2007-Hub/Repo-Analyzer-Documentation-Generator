import os
from typing import List, Dict, Any, Tuple
from app.models.schemas import FileInfo, ScanResult

class Scanner:
    BINARY_EXTENSIONS = {
        '.exe', '.dll', '.so', '.bin', '.pyc', '.jpg', '.jpeg', '.png',
        '.gif', '.pdf', '.zip', '.tar', '.gz', '.7z', '.iso', '.ico'
    }

    MINIFIED_EXTENSIONS = {'.min.js', '.min.css'}

    def __init__(self, max_files: int = 5000, max_file_kb: int = 500, max_repo_mb: int = 100):
        self.max_files = max_files
        self.max_file_kb = max_file_kb
        self.max_repo_mb = max_repo_mb

    def is_binary(self, file_path: str) -> bool:
        _, ext = os.path.splitext(file_path)
        if ext.lower() in self.BINARY_EXTENSIONS:
            return True

        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(1024)
                return b'\x00' in chunk
        except Exception:
            return True

    def count_lines(self, file_path: str) -> int:
        try:
            with open(file_path, 'rb') as f:
                return sum(1 for _ in f)
        except Exception:
            return 0

    def scan(self, repo_path: str, repo_name: str, commit_sha: str) -> ScanResult:
        files_info = []
        total_lines = 0
        total_size_bytes = 0

        # To build the file tree
        tree = {}

        for root, dirs, files in os.walk(repo_path):
            # Handle .gitignore basic (skip .git folder)
            if '.git' in dirs:
                dirs.remove('.git')

            if len(files_info) >= self.max_files:
                break

            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, repo_path)

                # Skip minified files
                if any(rel_path.endswith(ext) for ext in self.MINIFIED_EXTENSIONS):
                    continue

                try:
                    size_bytes = os.path.getsize(file_path)
                    size_kb = size_bytes / 1024

                    if size_kb > self.max_file_kb:
                        continue

                    total_size_bytes += size_bytes
                    if (total_size_bytes / (1024 * 1024)) > self.max_repo_mb:
                        break

                    binary = self.is_binary(file_path)
                    lines = 0 if binary else self.count_lines(file_path)

                    _, ext = os.path.splitext(file)

                    info = FileInfo(
                        path=rel_path,
                        size_kb=size_kb,
                        lines=lines,
                        extension=ext,
                        is_binary=binary
                    )
                    files_info.append(info)
                    total_lines += lines

                    # Build tree
                    parts = rel_path.split(os.sep)
                    curr = tree
                    for part in parts[:-1]:
                        curr = curr.setdefault(part, {})
                    curr[parts[-1]] = "file"
                except Exception:
                    continue

        return ScanResult(
            repository_name=repo_name,
            commit_sha=commit_sha,
            total_files=len(files_info),
            total_lines=total_lines,
            total_size_mb=total_size_bytes / (1024 * 1024),
            files=files_info,
            file_tree=tree
        )

    def print_tree(self, tree: Dict, indent: str = ""):
        for key, value in tree.items():
            if isinstance(value, dict):
                print(f"{indent}📁 {key}/")
                self.print_tree(value, indent + "  ")
            else:
                print(f"{indent}📄 {key}")
