import os
import re
from typing import List
from app.models.schemas import SecurityFinding

class SecurityAnalyzer:
    SECRET_PATTERNS = {
        'Generic API Key': r'(?i)(api[_-]?key|secret|token|password|auth_token)[\s]*[:=][\s]*[\'"]([a-zA-Z0-9_\-]{16,})[\'"]',
        'AWS Access Key': r'AKIA[0-9A-Z]{16}',
        'Private Key': r'-----BEGIN (RSA|OPENSSH|PRIVATE) KEY-----',
    }

    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def analyze(self, files_list: List[str], gitignore_content: str = "") -> List[SecurityFinding]:
        findings = []

        # 1. Check for .env file tracked in git
        # In this V1, we check if .env exists but isn't in the gitignore provided
        if os.path.exists(os.path.join(self.repo_path, ".env")):
            if ".env" not in gitignore_content:
                findings.append(SecurityFinding(
                    category="Secret Exposure",
                    severity="HIGH",
                    file=".env",
                    line=1,
                    description=".env file is committed to the repository"
                ))

        for file_path in files_list:
            # Skip binaries
            if any(file_path.endswith(ext) for ext in ['.exe', '.bin', '.jpg', '.png']):
                continue

            try:
                with open(os.path.join(self.repo_path, file_path), 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                    for i, line in enumerate(lines, 1):
                        # 2. Secret Detection
                        for category, pattern in self.SECRET_PATTERNS.items():
                            match = re.search(pattern, line)
                            if match:
                                # Mask the secret in the description
                                evidence = match.group(0)
                                masked = evidence[:10] + "..." + evidence[-5:] if len(evidence) > 15 else "********"
                                findings.append(SecurityFinding(
                                    category=category,
                                    severity="CRITICAL",
                                    file=file_path,
                                    line=i,
                                    description=f"Potential secret found: {masked}"
                                ))

                        # 3. Debug Mode
                        if any(x in line for x in ['DEBUG = True', 'debug: true', 'DEBUG=True']):
                            findings.append(SecurityFinding(
                                category="Configuration",
                                severity="MEDIUM",
                                file=file_path,
                                line=i,
                                description="Debug mode is enabled"
                            ))

                        # 4. Wildcard CORS
                        if 'CORS' in line and '*' in line:
                            findings.append(SecurityFinding(
                                category="Network Security",
                                severity="MEDIUM",
                                file=file_path,
                                line=i,
                                description="Wildcard CORS policy detected"
                            ))

                        # 5. SQL Injection (Basic)
                        if any(x in line for x in ['execute(', 'query(']) and 'f"' in line and '{' in line:
                            findings.append( obliged_finding := SecurityFinding(
                                category="SQL Injection",
                                severity="HIGH",
                                file=file_path,
                                line=i,
                                description="Potential SQL injection via f-string interpolation"
                            ))

            except Exception:
                continue

        return findings
