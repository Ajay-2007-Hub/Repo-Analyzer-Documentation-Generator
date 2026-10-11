import os
from typing import List, Dict, Any
from app.models.schemas import ScanResult, ProjectAnalysis, Endpoint, DatabaseInfo, AuthInfo, SecurityFinding

class ContextBuilder:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def build_context(
        self,
        scan_result: ScanResult,
        project_analysis: ProjectAnalysis,
        endpoints: List[Endpoint],
        db_info: DatabaseInfo,
        auth_info: AuthInfo,
        security_findings: List[SecurityFinding]
    ) -> str:

        context_parts = []

        # 1. Project Overview
        context_parts.append("### PROJECT OVERVIEW")
        context_parts.append(f"Repository: {scan_result.repository_name}")
        context_parts.append(f"Primary Languages: {', '.join(project_analysis.repo_info.languages.keys())}")
        context_parts.append(f"Frameworks: {', '.join(project_analysis.repo_info.frameworks)}")
        context_parts.append(f"Dependencies: {', '.join(project_analysis.repo_info.dependencies)}")
        if project_analysis.repo_info.readme_summary:
            context_parts.append(f"Summary: {project_analysis.repo_info.readme_summary}")
        context_parts.append("\n")

        # 2. API Endpoints
        context_parts.append("### API ENDPOINTS")
        if not endpoints:
            context_parts.append("No endpoints detected.")
        else:
            endpoint_lines = [f"{e.method} {e.path} ({e.file})" for e in endpoints]
            context_parts.append("\n".join(endpoint_lines))
        context_parts.append("\n")

        # 3. Infrastructure
        context_parts.append("### INFRASTRUCTURE")
        if db_info:
            context_parts.append(f"Database: {db_info.db_type}")
            context_parts.append(f"ORM: {db_info.orm}")
            context_parts.append(f"Models: {', '.join(db_info.models)}")
        else:
            context_parts.append("Database: Not detected")

        if auth_info:
            context_parts.append(f"Auth Mechanism: {auth_info.mechanism}")
            context_parts.append(f"Auth Deps: {', '.join(auth_info.dependencies)}")
        else:
            context_parts.append("Auth: Not detected")
        context_parts.append("\n")

        # 4. Security
        context_parts.append("### SECURITY FINDINGS")
        if not security_findings:
            context_parts.append("No security issues detected.")
        else:
            findings_lines = [f"[{f.severity}] {f.category}: {f.description} in {f.file}:{f.line}" for f in security_findings]
            context_parts.append("\n".join(findings_lines))
        context_parts.append("\n")

        # 5. Important File Snippets
        context_parts.append("### CRITICAL CODE SNIPPETS")
        for ranked_file in project_analysis.top_files:
            content = self._read_file_snippet(ranked_file.path)
            context_parts.append(f"--- File: {ranked_file.path} (Reason: {ranked_file.reason}) ---")
            context_parts.append(content)
            context_parts.append("\n")

        full_context = "\n".join(context_parts)

        # Strict prompt wrapping
        final_prompt = (
            "You are an expert software architect. Analyze the following repository context "
            "and provide a structured architectural analysis.\n\n"
            "CRITICAL RULES:\n"
            "1. Use ONLY the provided evidence.\n"
            "2. If information is missing, return 'Not detected'.\n"
            "3. Do NOT invent files, endpoints, or technologies.\n\n"
            f"{full_context}"
        )

        return final_prompt

    def _read_file_snippet(self, rel_path: str, max_lines: int = 50) -> str:
        try:
            full_path = os.path.join(self.repo_path, rel_path)
            if not os.path.exists(full_path):
                return "[File not found]"

            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                # If file is large, take the first 50 lines (often where imports/config are)
                snippet = "".join(lines[:max_lines])
                if len(lines) > max_lines:
                    snippet += "\n... [truncated]"
                return snippet
        except Exception as e:
            return f"[Error reading file: {str(e)}]"
