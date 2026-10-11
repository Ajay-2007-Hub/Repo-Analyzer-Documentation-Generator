import os
import re
from typing import List, Tuple, Optional
from app.models.schemas import ExternalService, AuthInfo, ScanResult

class ExternalAPIAnalyzer:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def analyze(self, scan_result: ScanResult) -> Tuple[List[ExternalService], Optional[AuthInfo]]:
        external_services = []
        auth_info = None

        # URL detection regex
        url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^"\s\)]+'

        # Auth signatures
        auth_sigs = {
            'JWT': ['PyJWT', 'jsonwebtoken', 'jwt.decode'],
            'OAuth2': ['oauth2', 'openid', 'auth0'],
            'Spring Security': ['spring-security', 'EnableWebSecurity'],
            'Passport.js': ['passport'],
        }

        detected_auth_deps = []
        domains = set()

        for file in scan_result.files:
            if file.is_binary:
                continue

            content = self._read_file(file.path)

            # 1. Detect External APIs
            urls = re.findall(url_pattern, content)
            for url in urls:
                # Extract domain
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                if domain and not any(x in domain for x in ['localhost', '127.0.0.1']):
                    domains.add(domain)

            # 2. Detect Auth
            for auth_type, sigs in auth_sigs.items():
                if any(sig.lower() in content.lower() for sig in sigs):
                    if auth_info is None:
                        auth_info = AuthInfo(mechanism=auth_type)
                    detected_auth_deps.append(auth_type)

        if auth_info:
            auth_info.dependencies = list(set(detected_auth_deps))

        external_services = [ExternalService(domain=d) for d in domains]

        return external_services, auth_info

    def _read_file(self, rel_path: str) -> str:
        try:
            with open(os.path.join(self.repo_path, rel_path), 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception:
            return ""
