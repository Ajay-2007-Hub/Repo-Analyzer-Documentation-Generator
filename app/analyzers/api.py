from typing import List
from app.models.schemas import Endpoint, ProjectAnalysis
from app.analyzers.api_python import PythonAPIAnalyzer
from app.analyzers.api_express import ExpressAPIAnalyzer
from app.analyzers.api_spring import SpringAPIAnalyzer

class APIAnalyzer:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def analyze(self, project_analysis: ProjectAnalysis) -> List[Endpoint]:
        all_endpoints = []
        frameworks = project_analysis.repo_info.frameworks

        # Gather all relevant files to avoid re-scanning the disk too many times
        # We use the top files and any file that looks like a route/controller
        relevant_files = []
        # Note: we should probably scan all source files for endpoints, not just top files
        # Since we have the scan result, we can just pass the file list.
        # For now, let's assume we'll pass the full list of non-binary files from a ScanResult.
        # (Wait, APIAnalyzer.analyze doesn't have the ScanResult, only ProjectAnalysis)
        # I'll modify the method signature to accept files.
        return [] # Placeholder, will implement in final version

    def analyze_with_files(self, files: List[str], project_analysis: ProjectAnalysis) -> List[Endpoint]:
        all_endpoints = []
        frameworks = project_analysis.repo_info.frameworks

        if "FastAPI" in frameworks or "Flask" in frameworks:
            analyzer = PythonAPIAnalyzer(self.repo_path)
            all_endpoints.extend(analyzer.analyze(files))

        if "Express" in frameworks:
            analyzer = ExpressAPIAnalyzer(self.repo_path)
            all_endpoints.extend(analyzer.analyze(files))

        if "Spring Boot" in frameworks:
            analyzer = SpringAPIAnalyzer(self.repo_path)
            all_endpoints.extend(analyzer.analyze(files))

        return all_endpoints
