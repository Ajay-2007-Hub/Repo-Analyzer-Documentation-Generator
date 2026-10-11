import os
import json
from typing import List, Dict, Any, Tuple, Set, Optional
from app.models.schemas import ScanResult, RepoInfo, RankedFile, ProjectAnalysis

class RepositoryAnalyzer:
    LANGUAGE_MAP = {
        '.py': 'Python',
        '.js': 'JavaScript',
        '.ts': 'TypeScript',
        '.jsx': 'JavaScript',
        '.tsx': 'TypeScript',
        '.java': 'Java',
        '.kt': 'Kotlin',
        '.cpp': 'C++',
        '.c': 'C',
        '.h': 'C++',
        '.go': 'Go',
        '.rs': 'Rust',
        '.rb': 'Ruby',
        '.php': 'PHP',
        '.swift': 'Swift',
        '.cs': 'C#',
    }

    FRAMEWORK_SIGNATURES = {
        'FastAPI': {'dependencies': ['fastapi'], 'files': ['main.py', 'app.py'], 'keywords': ['fastapi.FastAPI']},
        'Flask': {'dependencies': ['flask'], 'files': ['app.py'], 'keywords': ['flask.Flask']},
        'Express': {'dependencies': ['express'], 'files': ['index.js', 'app.js', 'server.js'], 'keywords': ['express()']},
        'Spring Boot': {'dependencies': ['spring-boot-starter'], 'files': ['Application.java'], 'keywords': ['@SpringBootApplication']},
        'React': {'dependencies': ['react'], 'files': ['App.js', 'index.js'], 'keywords': ['react']},
        'Next.js': {'dependencies': ['next'], 'files': ['pages/_app.js', 'app/page.tsx'], 'keywords': ['next/app', 'next/link']},
    }

    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def analyze(self, scan_result: ScanResult) -> ProjectAnalysis:
        languages = self._detect_languages(scan_result)
        dependencies, frameworks = self._detect_dependencies_and_frameworks()
        entry_points = self._detect_entry_points(scan_result)
        readme_summary = self._extract_readme_summary()

        repo_info = RepoInfo(
            languages=languages,
            frameworks=frameworks,
            dependencies=dependencies,
            entry_points=entry_points,
            readme_summary=readme_summary
        )

        top_files = self._rank_files(scan_result, frameworks)

        return ProjectAnalysis(
            repo_info=repo_info,
            top_files=top_files
        )

    def _detect_languages(self, scan_result: ScanResult) -> Dict[str, float]:
        lang_lines = {}
        total_lines = scan_result.total_lines

        if total_lines == 0:
            return {}

        for file in scan_result.files:
            # Use the mapped language name if available, otherwise keep the extension
            lang = self.LANGUAGE_MAP.get(file.extension, file.extension)
            lang_lines[lang] = lang_lines.get(lang, 0) + file.lines

        return {lang: (lines / total_lines) * 100 for lang, lines in lang_lines.items()}

    def _detect_dependencies_and_frameworks(self) -> Tuple[List[str], List[str]]:
        dependencies = set()
        frameworks = set()

        # Parse requirements.txt
        req_path = os.path.join(self.repo_path, "requirements.txt")
        if os.path.exists(req_path):
            try:
                with open(req_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            # Simple split for versions: fastapi==0.100 -> fastapi
                            dep = line.split('==')[0].split('>=')[0].split('<=')[0].strip()
                            dependencies.add(dep)
            except Exception: pass

        # Parse pyproject.toml (Simplified)
        toml_path = os.path.join(self.repo_path, "pyproject.toml")
        if os.path.exists(toml_path):
            try:
                with open(toml_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    # Very rough extraction for V1
                    import re
                    deps = re.findall(r'\"([a-zA-Z0-9\-_]+)\"', content)
                    dependencies.update(deps)
            except Exception: pass

        # Parse package.json
        pkg_path = os.path.join(self.repo_path, "package.json")
        if os.path.exists(pkg_path):
            try:
                with open(pkg_path, 'r', encoding='utf-8', errors='ignore') as f:
                    data = json.load(f)
                    deps = data.get('dependencies', {})
                    dev_deps = data.get('devDependencies', {})
                    dependencies.update(deps.keys())
                    dependencies.update(dev_deps.keys())
            except Exception: pass

        # Parse pom.xml (Simplified)
        pom_path = os.path.join(self.repo_path, "pom.xml")
        if os.path.exists(pom_path):
            try:
                with open(pom_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    import re
                    # Extract artifactId
                    artifacts = re.findall(r'<artifactId>(.*?)</artifactId>', content)
                    dependencies.update(artifacts)
            except Exception: pass

        # Framework Detection
        for framework, sig in self.FRAMEWORK_SIGNATURES.items():
            # Check dependencies
            if any(dep.lower() in [d.lower() for d in dependencies] for dep in sig['dependencies']):
                frameworks.add(framework)
                continue

            # Check for signature files
            for root, dirs, files in os.walk(self.repo_path):
                if any(f in files for f in sig['files']):
                    frameworks.add(framework)
                    break

        return list(dependencies), list(frameworks)

    def _detect_entry_points(self, scan_result: ScanResult) -> List[str]:
        entry_points = []
        common_entries = {'main.py', 'app.py', 'index.js', 'server.js', 'Application.java', 'manage.py'}

        for file in scan_result.files:
            filename = os.path.basename(file.path)
            if filename in common_entries:
                entry_points.append(file.path)

        return entry_points

    def _extract_readme_summary(self) -> Optional[str]:
        readme_path = os.path.join(self.repo_path, "README.md")
        if os.path.exists(readme_path):
            try:
                with open(readme_path, 'r', encoding='utf-8', errors='ignore') as f:
                    # Extract first 500 characters as summary
                    return f.read(500).strip() + "..."
            except Exception: pass
        return None

    def _rank_files(self, scan_result: ScanResult, frameworks: List[str]) -> List[RankedFile]:
        scored_files = []

        for file in scan_result.files:
            score = 0
            reasons = []
            path = file.path
            filename = os.path.basename(path)

            # High Score: Entry Points
            common_entries = {'main.py', 'app.py', 'index.js', 'server.js', 'Application.java'}
            if filename in common_entries:
                score += 50
                reasons.append("Entry point")

            # High Score: Config files
            if any(x in path for x in ['.env', 'settings.py', 'config.py', 'web.xml', 'application.properties']):
                score += 40
                reasons.append("Configuration")

            # Medium Score: Routes / Controllers / Models
            if any(x in path.lower() for x in ['route', 'controller', 'model', 'schema', 'api']):
                score += 20
                reasons.append("Core logic/API")

            # Low Score: Tests / Docs
            if 'test' in path.lower() or 'docs' in path.lower():
                score -= 20
                reasons.append("Test/Doc")

            if score > 0:
                scored_files.append(RankedFile(
                    path=path,
                    score=score,
                    reason=", ".join(reasons)
                ))

        # Sort by score descending and take top 10
        scored_files.sort(key=lambda x: x.score, reverse=True)
        return scored_files[:10]
