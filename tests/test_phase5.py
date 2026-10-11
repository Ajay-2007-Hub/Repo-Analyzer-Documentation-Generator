import pytest
from app.llm.ollama_client import OllamaClient
from app.llm.context import ContextBuilder
from app.models.schemas import (
    ScanResult, ProjectAnalysis, RepoInfo, FileInfo,
    Endpoint, DatabaseInfo, AuthInfo, SecurityFinding, RankedFile
)

@pytest.fixture
def ollama_client():
    return OllamaClient()

@pytest.fixture
def context_builder(tmp_path):
    # Setup a dummy repo path
    return ContextBuilder(str(tmp_path))

def test_ollama_connectivity(ollama_client):
    # This test might fail if Ollama is not running locally during CI/CD
    # but should pass on the developer machine.
    assert ollama_client.check_health() is True

def test_ollama_model_availability(ollama_client):
    assert ollama_client.is_model_available() is True

def test_context_builder_output(context_builder, tmp_path):
    # Setup dummy data
    scan_result = ScanResult(
        repository_name="test-repo",
        commit_sha="abc",
        total_files=1,
        total_lines=10,
        total_size_mb=0.1,
        files=[FileInfo(path="main.py", size_kb=1, lines=10, extension=".py", is_binary=False)],
        file_tree={}
    )

    project_analysis = ProjectAnalysis(
        repo_info=RepoInfo(
            languages={".py": 100.0},
            frameworks=["FastAPI"],
            dependencies=["fastapi", "uvicorn"],
            entry_points=["main.py"]
        ),
        top_files=[RankedFile(path="main.py", score=100, reason="Entry point")]
    )

    endpoints = [Endpoint(method="GET", path="/health", file="main.py", description="Health check")]
    db_info = DatabaseInfo(db_type="PostgreSQL", orm="SQLAlchemy", models=["User"])
    auth_info = AuthInfo(mechanism="JWT", dependencies=["PyJWT"])
    security_findings = [SecurityFinding(category="Config", severity="MEDIUM", file="app.py", line=1, description="Debug enabled")]

    (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()")

    prompt = context_builder.build_context(
        scan_result, project_analysis, endpoints, db_info, auth_info, security_findings
    )

    assert "PROJECT OVERVIEW" in prompt
    assert "API ENDPOINTS" in prompt
    assert "INFRASTRUCTURE" in prompt
    assert "SECURITY FINDINGS" in prompt
    assert "CRITICAL CODE SNIPPETS" in prompt
    assert "FastAPI" in prompt
    assert "/health" in prompt
    assert "PostgreSQL" in prompt
    assert " la la la" not in prompt # Should not contain random noise
