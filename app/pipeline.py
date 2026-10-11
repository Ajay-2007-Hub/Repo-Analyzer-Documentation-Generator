import os
from collections.abc import Callable
from pathlib import Path

from app.analyzers.api import APIAnalyzer
from app.analyzers.architecture import ArchitectureAnalyzer
from app.analyzers.database import DatabaseAnalyzer
from app.analyzers.external import ExternalAPIAnalyzer
from app.analyzers.repository import RepositoryAnalyzer
from app.analyzers.security import SecurityAnalyzer
from app.core.cloner import Cloner
from app.core.scanner import Scanner
from app.generators.diagram import DiagramGenerator
from app.generators.ppt import PowerPointGenerator
from app.generators.report import ReportGenerator
from app.models.analysis import AnalysisDocument, PipelineOutcome
from app.models.schemas import AuthInfo, DatabaseInfo

ProgressCallback = Callable[[str], None]


class AnalysisPipeline:
    """Run the repository analyzer stages and generate local artifacts."""

    def __init__(
        self,
        repositories_dir: str | Path = "repositories",
        outputs_dir: str | Path = "outputs",
        max_repo_mb: int | None = None,
        max_files: int | None = None,
        max_file_kb: int | None = None,
        cloner: Cloner | None = None,
        scanner: Scanner | None = None,
        repository_analyzer_cls: type[RepositoryAnalyzer] = RepositoryAnalyzer,
        api_analyzer_cls: type[APIAnalyzer] = APIAnalyzer,
        database_analyzer_cls: type[DatabaseAnalyzer] = DatabaseAnalyzer,
        external_analyzer_cls: type[ExternalAPIAnalyzer] = ExternalAPIAnalyzer,
        security_analyzer_cls: type[SecurityAnalyzer] = SecurityAnalyzer,
        architecture_analyzer: ArchitectureAnalyzer | None = None,
        diagram_generator: DiagramGenerator | None = None,
        report_generator: ReportGenerator | None = None,
        ppt_generator: PowerPointGenerator | None = None,
    ):
        self.repositories_dir = Path(repositories_dir)
        self.outputs_dir = Path(outputs_dir)
        self.repositories_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.cloner = cloner or Cloner(str(self.repositories_dir))
        self.scanner = scanner or Scanner(
            max_files=(
                max_files
                if max_files is not None
                else int(os.getenv("MAX_FILES", "5000"))
            ),
            max_file_kb=(
                max_file_kb
                if max_file_kb is not None
                else int(os.getenv("MAX_FILE_KB", "500"))
            ),
            max_repo_mb=(
                max_repo_mb
                if max_repo_mb is not None
                else int(os.getenv("MAX_REPO_MB", "100"))
            ),
        )
        self.repository_analyzer_cls = repository_analyzer_cls
        self.api_analyzer_cls = api_analyzer_cls
        self.database_analyzer_cls = database_analyzer_cls
        self.external_analyzer_cls = external_analyzer_cls
        self.security_analyzer_cls = security_analyzer_cls
        self.architecture_analyzer = architecture_analyzer
        self.diagram_generator = diagram_generator or DiagramGenerator(
            str(self.outputs_dir)
        )
        self.report_generator = report_generator or ReportGenerator(
            self.outputs_dir
        )
        self.ppt_generator = ppt_generator or PowerPointGenerator(
            self.outputs_dir
        )

    def run(
        self,
        repository_url: str,
        progress: ProgressCallback | None = None,
        github_token: str | None = None,
        repository_path: str | Path | None = None,
        commit_sha: str | None = None,
    ) -> PipelineOutcome:
        if not self.cloner.validate_url(repository_url):
            raise ValueError("URL must be https://github.com/<owner>/<repo>.")

        report_progress = progress or (lambda message: None)
        repo_name = self._repository_name(repository_url)
        owns_clone = repository_path is None
        repo_path = (
            Path(self.cloner.clone_repository(repository_url, token=github_token))
            if owns_clone
            else Path(repository_path)
        )
        try:
            commit_sha = commit_sha or self.cloner.get_commit_sha(str(repo_path))
            if not commit_sha or commit_sha.startswith("Unknown"):
                raise RuntimeError("Could not determine repository commit SHA.")

            report_progress("Scanning repository...")
            scan_result = self.scanner.scan(
                str(repo_path), repo_name, commit_sha
            )

            report_progress("Analyzing repository...")
            project_analysis = self.repository_analyzer_cls(
                str(repo_path)
            ).analyze(scan_result)

            report_progress("Analyzing APIs...")
            source_files = [
                file.path for file in scan_result.files if not file.is_binary
            ]
            api_analyzer = self.api_analyzer_cls(str(repo_path))
            endpoints = api_analyzer.analyze_with_files(
                source_files, project_analysis
            )

            report_progress("Analyzing database, authentication, external services, and security...")
            database = self.database_analyzer_cls(str(repo_path)).analyze(
                scan_result, project_analysis
            )
            db_info = database or DatabaseInfo(db_type="Not detected")
            external_services, auth_info = self.external_analyzer_cls(
                str(repo_path)
            ).analyze(scan_result)
            auth_info = auth_info or AuthInfo(mechanism="Not detected")
            security_analyzer = self.security_analyzer_cls(str(repo_path))
            gitignore_path = repo_path / ".gitignore"
            gitignore_content = (
                gitignore_path.read_text(encoding="utf-8", errors="ignore")
                if gitignore_path.is_file()
                else ""
            )
            security_findings = security_analyzer.analyze(
                source_files, gitignore_content=gitignore_content
            )

            report_progress("Analyzing architecture...")
            architecture_analyzer = (
                self.architecture_analyzer
                or ArchitectureAnalyzer(str(repo_path))
            )
            architecture = architecture_analyzer.analyze(
                scan_result,
                project_analysis,
                endpoints,
                db_info,
                auth_info,
                security_findings,
                external_services,
            )

            analysis = AnalysisDocument(
                scan=scan_result,
                project=project_analysis,
                endpoints=endpoints,
                database=database,
                authentication=(
                    auth_info if auth_info.mechanism != "Not detected" else None
                ),
                external_services=external_services,
                security_findings=security_findings,
                architecture=architecture,
            )

            report_progress("Generating architecture diagram...")
            diagram_outputs = self.diagram_generator.generate_all(
                architecture, repo_name
            )
            if not {"png", "svg"}.issubset(diagram_outputs):
                raise RuntimeError(
                    "Diagram generation failed to produce both PNG and SVG outputs."
                )

            report_progress("Generating report...")
            pdf_path = self.report_generator.generate(
                scan_result,
                project_analysis,
                endpoints,
                db_info=database,
                auth_info=analysis.authentication,
                external_services=external_services,
                security_findings=security_findings,
                architecture=architecture,
                diagram_path=diagram_outputs["png"],
            )

            report_progress("Generating presentation...")
            ppt_path = self.ppt_generator.generate(
                scan_result,
                project_analysis,
                endpoints,
                db_info=database,
                auth_info=analysis.authentication,
                external_services=external_services,
                security_findings=security_findings,
                architecture=architecture,
                diagram_path=diagram_outputs["png"],
            )

            outputs = {
                "pdf": str(pdf_path),
                "pptx": str(ppt_path),
                "json": str(self._write_analysis_json(analysis, repo_name)),
                "png": diagram_outputs["png"],
                "svg": diagram_outputs["svg"],
            }
            if "mermaid" in diagram_outputs:
                outputs["mermaid"] = diagram_outputs["mermaid"]
            return PipelineOutcome(
                commit_sha=commit_sha,
                analysis=analysis,
                outputs=outputs,
            )
        finally:
            if owns_clone:
                self.cloner.cleanup(str(repo_path))

    @staticmethod
    def _repository_name(repository_url: str) -> str:
        name = repository_url.rstrip("/").rsplit("/", 1)[-1]
        return name[:-4] if name.lower().endswith(".git") else name

    def _write_analysis_json(
        self, analysis: AnalysisDocument, repo_name: str
    ) -> Path:
        safe_name = "".join(
            char if char.isalnum() or char in "-_" else "_"
            for char in repo_name
        )
        destination = self.outputs_dir / f"{safe_name}_analysis.json"
        destination.write_text(
            analysis.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return destination
