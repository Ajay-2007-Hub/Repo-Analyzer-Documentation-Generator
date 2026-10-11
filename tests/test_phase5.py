from unittest.mock import Mock

import pytest
import requests
from pydantic import BaseModel

from app.llm.context import ContextBuilder
from app.llm.ollama_client import OllamaClient
from app.models.schemas import (
    AuthInfo,
    DatabaseInfo,
    Endpoint,
    ExternalService,
    FileInfo,
    ProjectAnalysis,
    RankedFile,
    RepoInfo,
    ScanResult,
    SecurityFinding,
)


class OllamaProbe(BaseModel):
    status: str


@pytest.fixture
def context_builder(tmp_path):
    return ContextBuilder(str(tmp_path))


def test_ollama_health_and_model_checks(monkeypatch):
    client = OllamaClient()
    response = Mock(status_code=200)
    response.json.return_value = {
        "models": [{"name": "qwen3-coder:latest"}, {"name": "other-model"}]
    }
    monkeypatch.setattr(requests, "get", Mock(return_value=response))

    assert client.check_health() is True
    assert client.is_model_available() is True


def test_ollama_model_check_rejects_partial_name_match(monkeypatch):
    client = OllamaClient()
    response = Mock(status_code=200)
    response.json.return_value = {"models": [{"name": "qwen3-coder-variant"}]}
    monkeypatch.setattr(requests, "get", Mock(return_value=response))

    assert client.is_model_available() is False


def test_ollama_structured_response_retries_validation_once(monkeypatch):
    client = OllamaClient()
    invalid_response = Mock()
    invalid_response.json.return_value = {"response": '{"wrong": "shape"}'}
    valid_response = Mock()
    valid_response.json.return_value = {"response": '{"status": "ready"}'}
    post = Mock(side_effect=[invalid_response, valid_response])
    monkeypatch.setattr(requests, "post", post)

    result = client.generate_structured(
        "Return status=ready as JSON.", OllamaProbe
    )

    assert result.status == "ready"
    assert post.call_count == 2
    first_payload = post.call_args_list[0].kwargs["json"]
    retry_payload = post.call_args_list[1].kwargs["json"]
    assert first_payload["format"] == OllamaProbe.model_json_schema()
    assert first_payload["options"]["temperature"] == 0.1
    assert first_payload["options"]["num_ctx"] == client.num_ctx
    assert "Validation error" in retry_payload["prompt"]


def test_ollama_structured_response_retries_transient_request(monkeypatch):
    client = OllamaClient()
    valid_response = Mock()
    valid_response.json.return_value = {"response": '{"status": "ready"}'}
    post = Mock(
        side_effect=[requests.Timeout("temporary timeout"), valid_response]
    )
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr("app.llm.ollama_client.time.sleep", Mock())

    assert client.generate_structured("prompt", OllamaProbe).status == "ready"
    assert post.call_count == 2


def test_context_builder_includes_facts_and_redacts_secrets(
    context_builder, tmp_path
):
    (tmp_path / "main.py").write_text(
        'from fastapi import FastAPI\nAPI_KEY = "sk-supersecret-value"\n'
        "app = FastAPI()\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "PASSWORD=do-not-send-this\n", encoding="utf-8"
    )

    scan_result = ScanResult(
        repository_name="test-repo",
        commit_sha="abc",
        total_files=1,
        total_lines=10,
        total_size_mb=0.1,
        files=[
            FileInfo(
                path="main.py",
                size_kb=1,
                lines=10,
                extension=".py",
                is_binary=False,
            )
        ],
        file_tree={},
    )
    project_analysis = ProjectAnalysis(
        repo_info=RepoInfo(
            languages={".py": 100.0},
            frameworks=["FastAPI"],
            dependencies=["fastapi", "uvicorn"],
            entry_points=["main.py"],
        ),
        top_files=[
            RankedFile(path="main.py", score=100, reason="Entry point"),
            RankedFile(path=".env", score=99, reason="Config file"),
        ],
    )
    endpoints = [
        Endpoint(
            method="GET",
            path="/health",
            file="main.py",
            description="Health check",
        )
    ]
    security_findings = [
        SecurityFinding(
            category="Configuration",
            severity="MEDIUM",
            file="app.py",
            line=1,
            description="Debug enabled",
        )
    ]

    prompt = context_builder.build_context(
        scan_result,
        project_analysis,
        endpoints,
        DatabaseInfo(db_type="PostgreSQL", orm="SQLAlchemy", models=["User"]),
        AuthInfo(mechanism="JWT", dependencies=["PyJWT"]),
        security_findings,
        [ExternalService(domain="api.example.com")],
    )

    assert "PROJECT OVERVIEW" in prompt
    assert "API ENDPOINTS" in prompt
    assert "INFRASTRUCTURE" in prompt
    assert "SECURITY FINDINGS" in prompt
    assert "CRITICAL CODE SNIPPETS" in prompt
    assert "FastAPI" in prompt
    assert "/health" in prompt
    assert "PostgreSQL" in prompt
    assert "api.example.com" in prompt
    assert "sk-supersecret-value" not in prompt
    assert "do-not-send-this" not in prompt
    assert "[REDACTED]" in prompt


def test_context_builder_enforces_budget_and_rejects_outside_paths(tmp_path):
    builder = ContextBuilder(str(tmp_path), token_budget=1200)
    outside_file = tmp_path.parent / "outside-secret.py"
    outside_file.write_text('TOKEN = "outside-secret-value"', encoding="utf-8")
    try:
        assert builder._read_file_snippet(str(outside_file)) == ""

        scan_result = ScanResult(
            repository_name="budget-test",
            commit_sha="abc",
            total_files=1,
            total_lines=10,
            total_size_mb=0.1,
            files=[],
            file_tree={},
        )
        project_analysis = ProjectAnalysis(
            repo_info=RepoInfo(
                languages={".py": 100},
                frameworks=["FastAPI"],
                dependencies=[f"dependency-{index}" for index in range(500)],
                entry_points=[],
            ),
            top_files=[],
        )
        endpoints = [
            Endpoint(
                method="GET",
                path=f"/resource/{index}",
                file="app.py",
                description="Get resource",
            )
            for index in range(500)
        ]
        prompt = builder.build_context(
            scan_result,
            project_analysis,
            endpoints,
            DatabaseInfo(db_type="Not detected"),
            AuthInfo(mechanism="Not detected"),
            [],
        )

        assert builder._estimated_tokens(prompt) <= builder.token_budget
        assert "additional items omitted" in prompt
    finally:
        outside_file.unlink(missing_ok=True)


def test_ollama_returns_valid_structured_output_ten_times():
    client = OllamaClient()
    if not client.check_health() or not client.is_model_available():
        pytest.skip("Ollama server or configured model is unavailable")

    for _ in range(10):
        result = client.generate_structured(
            'Use only the supplied data. Return {"status":"ready"}.',
            OllamaProbe,
        )
        assert result.status == "ready"
