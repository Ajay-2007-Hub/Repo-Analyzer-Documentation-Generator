import logging
import re
from pathlib import Path
from typing import ClassVar

from app.models.schemas import SecurityFinding

logger = logging.getLogger(__name__)


class SecurityAnalyzer:
    SECRET_PATTERNS: ClassVar[dict[str, re.Pattern[str]]] = {
        "Generic API Key": re.compile(
            r"""(?i)\b(api[_-]?key|secret|token|password|auth_token)"""
            r"""\s*[:=]\s*['"]([a-zA-Z0-9_\-]{16,})['"]"""
        ),
        "AWS Access Key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "Private Key": re.compile(
            r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PRIVATE) KEY-----"
        ),
    }
    SECRET_ASSIGNMENT = re.compile(
        r"""(?i)\b(?:api[_-]?key|secret|token|password|auth_token)\s*[:=]"""
    )

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()

    def analyze(
        self, files_list: list[str], gitignore_content: str = ""
    ) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        if not (self.repo_path / ".gitignore").is_file():
            findings.append(
                SecurityFinding(
                    category="Repository Hygiene",
                    severity="LOW",
                    file=".gitignore",
                    line=0,
                    description="Repository has no .gitignore file",
                )
            )

        env_file = self.repo_path / ".env"
        if env_file.is_file() and not self._is_ignored_env(gitignore_content):
            findings.append(
                SecurityFinding(
                    category="Secret Exposure",
                    severity="HIGH",
                    file=".env",
                    line=1,
                    description=".env file is present in the repository",
                )
            )

        for relative_path in files_list:
            if Path(relative_path).suffix.lower() in {
                ".exe",
                ".bin",
                ".jpg",
                ".jpeg",
                ".png",
                ".gif",
            }:
                continue
            candidate_path = self.repo_path / relative_path
            if candidate_path.is_symlink():
                continue
            file_path = candidate_path.resolve()
            if not file_path.is_relative_to(self.repo_path):
                logger.warning("Skipping security scan path outside repository: %s", relative_path)
                continue
            try:
                if file_path.is_symlink() or not file_path.is_file():
                    continue
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                logger.warning("Could not read file for security analysis: %s", relative_path)
                continue

            for line_number, line in enumerate(content.splitlines(), 1):
                for category, pattern in self.SECRET_PATTERNS.items():
                    if pattern.search(line):
                        findings.append(
                            SecurityFinding(
                                category=category,
                                severity="CRITICAL",
                                file=relative_path,
                                line=line_number,
                                description="Potential secret detected; value redacted",
                            )
                        )
                if self.SECRET_ASSIGNMENT.search(line) and not any(
                    finding.file == relative_path
                    and finding.line == line_number
                    and finding.severity == "CRITICAL"
                    for finding in findings
                ):
                    findings.append(
                        SecurityFinding(
                            category="Potential Secret",
                            severity="HIGH",
                            file=relative_path,
                            line=line_number,
                            description="Potential credential assignment detected; value redacted",
                        )
                    )

                if re.search(r"\bDEBUG\s*[:=]\s*true\b", line, re.IGNORECASE):
                    findings.append(
                        SecurityFinding(
                            category="Configuration",
                            severity="MEDIUM",
                            file=relative_path,
                            line=line_number,
                            description="Debug mode is enabled",
                        )
                    )

                if re.search(r"CORS", line, re.IGNORECASE) and "*" in line:
                    findings.append(
                        SecurityFinding(
                            category="Network Security",
                            severity="MEDIUM",
                            file=relative_path,
                            line=line_number,
                            description="Wildcard CORS policy detected",
                        )
                    )

                if self._has_sql_interpolation(line):
                    findings.append(
                        SecurityFinding(
                            category="SQL Injection",
                            severity="HIGH",
                            file=relative_path,
                            line=line_number,
                            description="Potential SQL query interpolation detected",
                        )
                    )
        return findings

    @staticmethod
    def _is_ignored_env(gitignore_content: str) -> bool:
        return any(
            line.strip() in {".env", ".env/", ".env*"}
            for line in gitignore_content.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )

    @staticmethod
    def _has_sql_interpolation(line: str) -> bool:
        query_call = re.search(r"\b(?:execute|query)\s*\(", line, re.IGNORECASE)
        if not query_call:
            return False
        return bool(
            re.search(r"""f['"]""", line)
            or re.search(r"""['"][^'"]*['"]\s*\+""", line)
            or re.search(r"""['"][^'"]*%s?['"]\s*%""", line)
        )
