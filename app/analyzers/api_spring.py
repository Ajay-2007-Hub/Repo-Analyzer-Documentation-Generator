import re
import os
from typing import List
from app.models.schemas import Endpoint

class SpringAPIAnalyzer:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def analyze(self, files: List[str]) -> List[Endpoint]:
        endpoints = []

        for file_path in files:
            if not file_path.endswith('.java'):
                continue

            try:
                with open(os.path.join(self.repo_path, file_path), 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                    # Find class-level @RequestMapping
                    class_prefix = ""
                    class_match = re.search(r'@RequestMapping\(\s*value\s*=\s*[\'"]([^\'"]+)[\'"]\s*\)', content)
                    if not class_match:
                        class_match = re.search(r'@RequestMapping\([\'"]([^\'"]+)[\'"]\)', content)

                    if class_match:
                        class_prefix = class_match.group(1)

                    # Find method-level endpoints
                    # Pattern: @(GetMapping|PostMapping|...)("\path")
                    method_pattern = r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|RequestMapping)\([\'"]([^\'"]+)[\'"]\)'
                    matches = re.finditer(method_pattern, content)

                    for match in matches:
                        anno, path = match.groups()

                        # Determine method
                        method = "GET"
                        if "PostMapping" in anno: method = "POST"
                        elif "PutMapping" in anno: method = "PUT"
                        elif "DeleteMapping" in anno: method = "DELETE"
                        elif "RequestMapping" in anno: method = "ALL"

                        full_path = (class_prefix + path).replace("//", "/")

                        endpoints.append(Endpoint(
                            method=method,
                            path=full_path,
                            file=file_path,
                            description="Spring Boot endpoint"
                        ))
            except Exception:
                continue

        return endpoints
