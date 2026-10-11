from unittest.mock import Mock

import pytest
import requests
from git import GitCommandError

from app.analyzers.api_python import PythonAPIAnalyzer
from app.analyzers.security import SecurityAnalyzer
from app.core.cloner import Cloner
from app.core.scanner import Scanner
from app.llm.ollama_client import OllamaClient
from app.models.schemas import ProjectAnalysis


def test_scanner_honors_gitignore_size_file_and_symlink_limits(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".gitignore").write_text(
        "*.log\nnode_modules/\n", encoding="utf-8"
    )
    (repository / "keep.py").write_text("one\ntwo\n", encoding="utf-8")
    (repository / "ignored.log").write_text("secret log", encoding="utf-8")
    (repository / "large.py").write_bytes(b"x" * 2048)
    ignored_directory = repository / "node_modules"
    ignored_directory.mkdir()
    (ignored_directory / "dependency.js").write_text("ignored", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("outside repository", encoding="utf-8")
    try:
        (repository / "outside-link.py").symlink_to(outside)
    except OSError:
        pass

    result = Scanner(max_files=50, max_file_kb=1, max_repo_mb=1).scan(
        str(repository), "sample", "sha"
    )

    assert [file.path for file in result.files] == [".gitignore", "keep.py"]
    assert result.total_files == 2
    assert result.total_lines == 4
    assert result.file_tree["keep.py"] == "file"


def test_scanner_handles_empty_non_utf8_large_and_bounded_repositories(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    empty_result = Scanner().scan(str(empty), "empty", "sha")
    assert empty_result.total_files == 0
    assert empty_result.total_lines == 0

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_bytes(b"valid\n\xff-invalid\n")
    (repo / "b.txt").write_text("two\nlines\n", encoding="utf-8")
    (repo / "c.txt").write_text("more\n", encoding="utf-8")

    file_limited = Scanner(max_files=2, max_file_kb=10, max_repo_mb=10).scan(
        str(repo), "bounded", "sha"
    )
    assert file_limited.total_files == 2
    assert {file.path for file in file_limited.files} == {"a.txt", "b.txt"}
    assert file_limited.total_lines == 4

    repo_limited = Scanner(max_files=20, max_file_kb=10, max_repo_mb=1).scan(
        str(repo), "bounded", "sha"
    )
    assert repo_limited.total_size_mb <= 1 / 1024

    byte_limited_repo = tmp_path / "byte-limited"
    byte_limited_repo.mkdir()
    (byte_limited_repo / "a.txt").write_bytes(b"a" * (600 * 1024))
    (byte_limited_repo / "b.txt").write_bytes(b"b" * (600 * 1024))
    byte_limited = Scanner(
        max_files=20, max_file_kb=700, max_repo_mb=1
    ).scan(str(byte_limited_repo), "byte-limited", "sha")
    assert [file.path for file in byte_limited.files] == ["a.txt"]
    assert byte_limited.total_size_mb <= 1

    with pytest.raises(ValueError, match="must be positive"):
        Scanner(max_files=0)


def test_cloner_url_validation_and_cleanup_boundaries(tmp_path):
    cloner = Cloner(str(tmp_path / "repositories"))
    assert cloner.validate_url("https://github.com/owner/repo")
    assert cloner.validate_url("https://github.com/owner/repo.git")
    assert not cloner.validate_url("https://github.com/owner/../outside")
    assert not cloner.validate_url("https://user:password@github.com/owner/repo")
    assert not cloner.validate_url("https://github.com/owner/repo?download=true")
    assert not cloner.validate_url("https://github.com.evil.example/owner/repo")

    protected = cloner.base_dir / "keep.txt"
    protected.write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="inside the configured"):
        cloner.cleanup(str(cloner.base_dir))
    with pytest.raises(ValueError, match="inside the configured"):
        cloner.cleanup(str(tmp_path))
    assert protected.read_text(encoding="utf-8") == "preserve"


def test_cloner_clone_failure_does_not_leak_github_token(tmp_path, monkeypatch):
    cloner = Cloner(str(tmp_path / "repositories"))
    monkeypatch.setattr(
        "app.core.cloner.Repo.clone_from",
        Mock(
            side_effect=GitCommandError(
                "clone", 128, stderr="https://private-token@github.com/not-found"
            )
        ),
    )
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN") as error:
        cloner.clone_repository(
            "https://github.com/owner/private-repo",
            token="private-token",
        )
    assert "private-token" not in str(error.value)
    assert not (cloner.base_dir / "owner" / "private-repo").exists()


def test_security_analyzer_redacts_secrets_and_reports_missing_gitignore(tmp_path):
    source = tmp_path / "app.py"
    secret = "sk-live-super-secret-123456"
    source.write_text(
        f'API_KEY = "{secret}"\n'
        "DEBUG=True\n"
        "CORS_ALLOW_ORIGINS = '*'\n"
        'db.execute(f"SELECT * FROM users WHERE name={name}")\n',
        encoding="utf-8",
    )
    findings = SecurityAnalyzer(str(tmp_path)).analyze(["app.py"])

    descriptions = " ".join(finding.description for finding in findings)
    categories = {finding.category for finding in findings}
    assert secret not in descriptions
    assert "Potential secret detected; value redacted" in descriptions
    assert "Repository Hygiene" in categories
    assert "Configuration" in categories
    assert "Network Security" in categories
    assert "SQL Injection" in categories


def test_security_analyzer_ignores_external_symlinks(tmp_path):
    outside = tmp_path.parent / "outside-secrets.py"
    outside.write_text('API_KEY = "really-long-external-secret"', encoding="utf-8")
    link = tmp_path / "linked.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is not permitted on this platform")

    findings = SecurityAnalyzer(str(tmp_path)).analyze(["linked.py"])
    assert not any(finding.severity == "CRITICAL" for finding in findings)
    outside.unlink(missing_ok=True)


def test_api_analyzer_survives_syntax_errors_and_non_utf8_sources(tmp_path):
    (tmp_path / "broken.py").write_text(
        "from fastapi import FastAPI\n@app.get('/broken'\n", encoding="utf-8"
    )
    (tmp_path / "binary.py").write_bytes(b"\xff\xfe\x00\x80")
    (tmp_path / "valid.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/health')\n"
        "def health():\n    return {'ok': True}\n",
        encoding="utf-8",
    )

    endpoints = PythonAPIAnalyzer(str(tmp_path)).analyze(
        ["broken.py", "binary.py", "valid.py"]
    )
    assert [(endpoint.method, endpoint.path) for endpoint in endpoints] == [
        ("GET", "/health")
    ]


def test_ollama_invalid_json_retries_once_then_surfaces_failure(monkeypatch):
    client = OllamaClient()
    invalid = Mock()
    invalid.json.return_value = {"response": "{not valid JSON"}
    post = Mock(return_value=invalid)
    monkeypatch.setattr("app.llm.ollama_client.requests.post", post)

    class ResponseSchema(ProjectAnalysis):
        pass

    with pytest.raises(RuntimeError, match="invalid structured output"):
        client.generate_structured("Return schema JSON", ResponseSchema)
    assert post.call_count == 2


def test_ollama_health_check_handles_offline_server(monkeypatch):
    client = OllamaClient()
    monkeypatch.setattr(
        "app.llm.ollama_client.requests.get",
        Mock(side_effect=requests.ConnectionError("offline")),
    )
    assert client.check_health() is False
