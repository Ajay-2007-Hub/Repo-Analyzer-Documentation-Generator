import re
import os
from typing import List
from app.models.schemas import Endpoint

class ExpressAPIAnalyzer:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def analyze(self, files: List[str]) -> List[Endpoint]:
        endpoints = []
        # Simple prefix tracking: prefix -> router_name
        # In a real project, we'd parse app.use('/api', router)
        router_prefixes = {}

        # First pass: try to find app.use('/prefix', routerName)
        for file_path in files:
            if not file_path.endswith(('.js', '.ts', '.jsx', '.tsx')):
                continue

            try:
                with open(os.path.join(self.repo_path, file_path), 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    # Regex for app.use('/prefix', routerName)
                    matches = re.findall(r'app\.use\(\s*[\'"]([^\'"]+)[\'"]\s*,\s*([a-zA-Z0-9_]+)\s*\)', content)
                    for prefix, router in matches:
                        router_prefixes[router] = prefix
            except Exception:
                continue

        # Second pass: find endpoints
        for file_path in files:
            if not file_path.endswith(('.js', '.ts', '.jsx', '.tsx')):
                continue

            try:
                with open(os.path.join(self.repo_path, file_path), 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                    for line in lines:
                        # Match: router.get('/path', ...) or app.post('/path', ...)
                        # Pattern: (router|app)\.(get|post|put|delete|patch)\(['"]([^'"]+)['"]
                        match = re.search(r'([a-zA-Z0-9_]+)\.(get|post|put|delete|patch)\(\s*[\'"]([^\'"]+)[\'"]', line)
                        if match:
                            obj_name, method, path = match.groups()
                            method = method.upper()

                            prefix = router_prefixes.get(obj_name, "")
                            full_path = (prefix + path).replace("//", "/")

                            endpoints.append(Endpoint(
                                method=method,
                                path=full_path,
                                file=file_path,
                                description="Express endpoint"
                            ))
            except Exception:
                continue

        return endpoints
