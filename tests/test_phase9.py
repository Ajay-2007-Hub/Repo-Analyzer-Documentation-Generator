import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.manager import AnalysisManager
from app.analyzers.external import ExternalAPIAnalyzer
from app.core.db import SQLiteStore
from app.main import app
from app.models.analysis import AnalysisDocument, PipelineOutcome
from app.models.architecture import ArchitectureGraph, ArchNode
from app.models.schemas import (
    AuthInfo,
    DatabaseInfo,
    Endpoint,
    FileInfo,
    ProjectAnalysis,
    RepoInfo,
    ScanResult,
)
from app.pipeline import AnalysisPipeline


class StubCloner:
    def __init__(self, repository_path: Path, commit_sha: str = "abc123"):
        self.repository_path = repository_path
        self.commit_sha = commit_sha
        self.cleaned = []
        self.clone_count = 0

    def validate_url(self, url: str) -> bool:
        return url.startswith("https://github.com/")

    def clone_repository(self, url: str, token: str | None = None) -> str:
        self.clone_count += 1
        return str(self.repository_path)

    def get_commit_sha(self, path: str) -> str:
        return self.commit_sha

    def cleanup(self, path: str) -> None:
        self.cleaned.append(path)


class StubPipeline:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.cloner = None
        self.calls = 0

    def run(
        self,
        repository_url: str,
        progress=None,
        github_token=None,
        repository_path=None,
        commit_sha=None,
    ) -> PipelineOutcome:
        self.calls += 1
        if progress:
            progress("Generating report...")
        outputs = {}
        for output_type in ("pdf", "pptx", "json", "png", "svg"):
            path = self.output_dir / f"artifact.{output_type}"
            path.write_bytes(b"test output")
            outputs[output_type] = str(path)
        return PipelineOutcome(
            commit_sha=commit_sha or "abc123",
            analysis=sample_analysis(),
            outputs=outputs,
        )


def sample_analysis() -> AnalysisDocument:
    return AnalysisDocument(
        scan=ScanResult(
            repository_name="service",
            commit_sha="abc123",
            total_files=1,
            total_lines=1,
            total_size_mb=0.1,
            files=[
                FileInfo(
                    path="main.py",
                    size_kb=0.1,
                    lines=1,
                    extension=".py",
                    is_binary=False,
                )
            ],
            file_tree={},
        ),
        project=ProjectAnalysis(
            repo_info=RepoInfo(
                languages={"Python": 100},
                frameworks=["FastAPI"],
                dependencies=["fastapi"],
                entry_points=["main.py"],
            ),
            top_files=[],
        ),
        endpoints=[
            Endpoint(
                method="GET",
                path="/health",
                file="main.py",
                description="Health endpoint",
            )
        ],
        database=DatabaseInfo(db_type="SQLite"),
        authentication=AuthInfo(mechanism="JWT"),
        architecture=ArchitectureGraph(
            nodes=[
                ArchNode(id="api", label="API", node_type="backend")
            ]
        ),
    )


def wait_for_status(manager: AnalysisManager, run_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = manager.get_status(run_id)
        if result and result["status"] in {"completed", "failed"}:
            return result
        time.sleep(0.01)
    raise AssertionError("Background run did not finish within the timeout")


def test_sqlite_run_lifecycle_and_commit_cache(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    store = SQLiteStore(tmp_path / "database.sqlite3")
    cloner = StubCloner(repository)
    pipeline = StubPipeline(tmp_path)
    pipeline.cloner = cloner
    manager = AnalysisManager(store=store, pipeline=pipeline, cloner=cloner)
    url = "https://github.com/example/service"

    first_run = manager.start(url)
    assert wait_for_status(manager, first_run)["status"] == "completed"
    results = manager.get_results(first_run)
    assert results["analysis"]["scan"]["repository_name"] == "service"
    assert set(results["outputs"]) >= {"pdf", "pptx", "json", "png", "svg"}
    assert manager.get_download(first_run, "pdf").is_file()

    second_run = manager.start(url)
    assert wait_for_status(manager, second_run)["status"] == "completed"
    assert pipeline.calls == 1
    assert cloner.clone_count == 2
    assert store.get_run(second_run)["commit_sha"] == "abc123"
    assert cloner.cleaned == [str(repository), str(repository)]

    cloner.commit_sha = "newsha"
    third_run = manager.start(url)
    assert wait_for_status(manager, third_run)["status"] == "completed"
    assert pipeline.calls == 2

    with pytest.raises(ValueError, match="Unsupported download type"):
        manager.get_download(first_run, "exe")


def test_sqlite_rejects_updates_for_unknown_run(tmp_path):
    store = SQLiteStore(tmp_path / "database.sqlite3")
    with pytest.raises(KeyError):
        store.update_progress("missing", "Scanning repository...")


def test_pipeline_uses_configured_scan_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_REPO_MB", "12")
    monkeypatch.setenv("MAX_FILES", "345")
    monkeypatch.setenv("MAX_FILE_KB", "67")

    pipeline = AnalysisPipeline(
        repositories_dir=tmp_path / "repositories",
        outputs_dir=tmp_path / "outputs",
    )

    assert pipeline.scanner.max_repo_mb == 12
    assert pipeline.scanner.max_files == 345
    assert pipeline.scanner.max_file_kb == 67


def test_manager_marks_failure_without_persisting_clone_token(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    cloner = StubCloner(repository)

    class FailingPipeline:
        def __init__(self):
            self.cloner = cloner

        def run(self, *args, **kwargs):
            raise RuntimeError(
                "clone failed for https://private-token@github.com/example/service"
            )

    manager = AnalysisManager(
        store=SQLiteStore(tmp_path / "failed.sqlite3"),
        pipeline=FailingPipeline(),
        cloner=cloner,
        github_token="private-token",
    )
    run_id = manager.start("https://github.com/example/service")
    status = wait_for_status(manager, run_id)

    assert status["status"] == "failed"
    assert "RuntimeError" in status["error"]
    assert "private-token" not in status["error"]
    assert cloner.cleaned == [str(repository)]


def test_external_service_detection_discards_url_credentials(tmp_path):
    source = tmp_path / "main.py"
    source.write_text(
        "client = 'https://user:super-secret@Api.Example.com:8443/path'\n",
        encoding="utf-8",
    )
    scan = ScanResult(
        repository_name="service",
        commit_sha="abc123",
        total_files=1,
        total_lines=1,
        total_size_mb=0.1,
        files=[
            FileInfo(
                path="main.py",
                size_kb=1,
                lines=1,
                extension=".py",
                is_binary=False,
            )
        ],
        file_tree={},
    )

    services, _ = ExternalAPIAnalyzer(str(tmp_path)).analyze(scan)

    assert [service.domain for service in services] == ["api.example.com"]
    assert "super-secret" not in str(services)


def test_pipeline_uses_analyzers_and_cleans_owned_repository(tmp_path):
    repository = tmp_path / "cloned"
    repository.mkdir()
    (repository / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "@app.get('/health')\ndef health():\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    (repository / "requirements.txt").write_text(
        "fastapi\n", encoding="utf-8"
    )
    (repository / ".gitignore").write_text(".env\n", encoding="utf-8")
    output_dir = tmp_path / "outputs"
    cloner = StubCloner(repository)

    class FakeDiagramGenerator:
        def generate_all(self, graph, repo_name):
            output_dir.mkdir(exist_ok=True)
            paths = {}
            for output_type in ("png", "svg", "mermaid"):
                path = output_dir / f"architecture.{output_type}"
                path.write_bytes(b"diagram")
                paths[output_type] = str(path)
            return paths

    class FakeReportGenerator:
        def generate(self, *args, **kwargs):
            path = output_dir / "report.pdf"
            path.write_bytes(b"%PDF-")
            return path

    class FakePptGenerator:
        def generate(self, *args, **kwargs):
            path = output_dir / "presentation.pptx"
            path.write_bytes(b"pptx")
            return path

    class FakeArchitectureAnalyzer:
        def analyze(self, *args):
            return ArchitectureGraph(
                nodes=[ArchNode(id="api", label="API", node_type="backend")]
            )

    pipeline = AnalysisPipeline(
        repositories_dir=tmp_path / "repositories",
        outputs_dir=output_dir,
        cloner=cloner,
        diagram_generator=FakeDiagramGenerator(),
        report_generator=FakeReportGenerator(),
        ppt_generator=FakePptGenerator(),
        architecture_analyzer=FakeArchitectureAnalyzer(),
    )
    progress = []
    result = pipeline.run(
        "https://github.com/example/service",
        progress=progress.append,
    )

    assert result.commit_sha == "abc123"
    assert result.analysis.scan.repository_name == "service"
    assert result.analysis.endpoints[0].path == "/health"
    assert Path(result.outputs["json"]).is_file()
    assert json.loads(Path(result.outputs["json"]).read_text())["scan"]["commit_sha"] == "abc123"
    assert cloner.cleaned == [str(repository)]
    assert progress[0] == "Scanning repository..."
    assert progress[-1] == "Generating presentation..."


def test_fastapi_routes_validate_and_expose_downloads(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    store = SQLiteStore(tmp_path / "api.sqlite3")
    cloner = StubCloner(repository)
    pipeline = StubPipeline(tmp_path)
    pipeline.cloner = cloner
    manager = AnalysisManager(store=store, pipeline=pipeline, cloner=cloner)
    monkeypatch.setattr("app.main.manager", manager)
    client = TestClient(app)

    invalid = client.post(
        "/analyze", json={"repository_url": "https://example.com/not-github"}
    )
    assert invalid.status_code == 422

    accepted = client.post(
        "/analyze",
        json={"repository_url": "https://github.com/example/service"},
    )
    assert accepted.status_code == 202
    run_id = accepted.json()["id"]
    assert wait_for_status(manager, run_id)["status"] == "completed"

    assert client.get(f"/status/{run_id}").json()["status"] == "completed"
    results = client.get(f"/results/{run_id}")
    assert results.status_code == 200
    assert results.json()["analysis"]["endpoints"][0]["path"] == "/health"

    download = client.get(f"/download/{run_id}/json")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/json")
    assert download.content.startswith(b"test output")
    assert client.get(f"/download/{run_id}/exe").status_code == 404
    assert client.get("/status/unknown").status_code == 404
