import ast
import os
from typing import List, Dict, Tuple, Optional
from app.models.schemas import Endpoint

class PythonAPIAnalyzer:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def analyze(self, files: List[str]) -> List[Endpoint]:
        endpoints = []
        # We need to track router prefixes for FastAPI
        router_prefixes = {} # router_name -> prefix

        # First pass: Detect APIRouters and their prefixes
        for file_path in files:
            if not file_path.endswith('.py'):
                continue

            try:
                with open(os.path.join(self.repo_path, file_path), 'r', encoding='utf-8', errors='ignore') as f:
                    tree = ast.parse(f.read())
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Assign):
                            # Detect: router = APIRouter(prefix="/users")
                            if isinstance(node.value, ast.Call):
                                if getattr(node.value.func, 'attr', None) == 'APIRouter' or \
                                   (isinstance(node.value.func, ast.Name) and node.value.func.id == 'APIRouter'):

                                    target_name = None
                                    if isinstance(node.targets[0], ast.Name):
                                        target_name = node.targets[0].id

                                    prefix = ""
                                    for kw in node.value.keywords:
                                        if kw.arg == 'prefix' and isinstance(kw.value, ast.Constant):
                                            prefix = kw.value.value

                                    if target_name:
                                        router_prefixes[target_name] = prefix
            except Exception:
                continue

        # Second pass: Detect endpoints
        for file_path in files:
            if not file_path.endswith('.py'):
                continue

            try:
                with open(os.path.join(self.repo_path, file_path), 'r', encoding='utf-8', errors='ignore') as f:
                    tree = ast.parse(f.read())
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            for decorator in node.decorator_list:
                                if isinstance(decorator, ast.Call):
                                    # FastAPI: @router.get("/") or @app.get("/")
                                    if isinstance(decorator.func, ast.Attribute):
                                        func_name = decorator.func.attr
                                        if func_name in ['get', 'post', 'put', 'delete', 'patch']:
                                            method = func_name.upper()
                                            path = ""
                                            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                                                path = decorator.args[0].value

                                            # Try to resolve router prefix
                                            router_name = ""
                                            if isinstance(decorator.func.value, ast.Name):
                                                router_name = decorator.func.value.id

                                            prefix = router_prefixes.get(router_name, "")
                                            full_path = (prefix + path).replace("//", "/")

                                            endpoints.append(Endpoint(
                                                method=method,
                                                path=full_path,
                                                file=file_path,
                                                description=ast.get_docstring(node) or "No description"
                                            ))

                                            # Handle Flask @app.route("/", methods=['GET'])
                                            # Note: This simple AST visitor handles both if decorators match

                            # Flask: @app.route("/")
                            for decorator in node.decorator_list:
                                if isinstance(decorator, ast.Call):
                                    if isinstance(decorator.func, ast.Attribute) and decorator.func.attr == 'route':
                                        method = "GET" # Default
                                        path = ""
                                        if decorator.args and isinstance(decorator.args[0], ast.Constant):
                                            path = decorator.args[0].value

                                        # Check for methods keyword
                                        for kw in decorator.keywords:
                                            if kw.arg == 'methods' and isinstance(kw.value, ast.List):
                                                methods = [elt.value for elt in kw.value.elts if isinstance(elt, ast.Constant)]
                                                method = ", ".join(methods) if methods else "GET"

                                        endpoints.append(Endpoint(
                                            method=method,
                                            path=path,
                                            file=file_path,
                                            description=ast.get_docstring(node) or "No description"
                                        ))
            except Exception:
                continue

        return endpoints
