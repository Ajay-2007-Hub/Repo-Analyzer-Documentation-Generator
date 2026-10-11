import pytest
from app.core.cloner import Cloner
from app.core.scanner import Scanner
from app.analyzers.repository import RepositoryAnalyzer
import os
import shutil

@pytest.fixture
def setup_repo(tmp_path):
    # Create a dummy FastAPI-like structure
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    (repo_dir / "requirements.txt").write_text("fastapi\nuvicorn")
    (repo_dir / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()")
    (repo_dir / "models.py").write_text("class User: pass")

    # Create routes directory
    routes_dir = repo_dir / "routes"
    routes_dir.mkdir()
    (routes_dir / "users.py").write_text("from fastapi import APIRouter\nrouter = APIRouter()")

    (repo_dir / "README.md").write_text("This is a test project.")

    tests_dir = repo_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_main.py").write_text("def test_all(): pass")

    return repo_dir

def test_repository_analyzer_fastapi(setup_repo):
    repo_path = str(setup_repo)

    # Mock ScanResult
    # In real life we'd use scanner.scan(), but we'll build a simple one for unit test
    from app.models.schemas import ScanResult, FileInfo

    files = [
        FileInfo(path="main.py", size_kb=1.0, lines=2, extension=".py", is_binary=False),
        FileInfo(path="models.py", size_kb=1.0, lines=1, extension=".py", is_binary=False),
        FileInfo(path="routes/users.py", size_kb=1.0, lines=2, extension=".py", is_binary=False),
        FileInfo(path="README.md", size_kb=1.0, lines=1, extension=".md", is_binary=False),
        FileInfo(path="tests/test_main.py", size_kb=1.0, lines=1, extension=".py", is_binary=False),
    ]

    scan_result = ScanResult(
        repository_name="test_repo",
        commit_sha="12345",
        total_files=5,
        total_lines=7,
        total_size_mb=0.005,
        files=files,
        file_tree={}
    )

    analyzer = RepositoryAnalyzer(repo_path)
    analysis = analyzer.analyze(scan_result)

    assert "FastAPI" in analysis.repo_info.frameworks
    assert "fastapi" in analysis.repo_info.dependencies
    assert analysis.repo_info.languages['Python'] > 0
    assert any(f.path == "main.py" for f in analysis.top_files)
    assert analysis.repo_info.readme_summary is not None

def test_repository_analyzer_express(tmp_path):
    repo_dir = tmp_path / "express_repo"
    repo_dir.mkdir()
    (repo_dir / "package.json").write_text('{"dependencies": {"express": "^4.17.1"}}')
    (repo_dir / "index.js").write_text("const express = require('express');")

    from app.models.schemas import ScanResult, FileInfo
    files = [
        FileInfo(path="package.json", size_kb=1.0, lines=1, extension=".json", is_binary=False),
        FileInfo(path="index.js", size_kb=1.0, lines=1, extension=".js", is_binary=False),
    ]
    scan_result = ScanResult(
        repository_name="express_repo",
        commit_sha="12345",
        total_files=2,
        total_lines=2,
        total_size_mb=0.002,
        files=files,
        file_tree={}
    )

    analyzer = RepositoryAnalyzer(str(repo_dir))
    analysis = analyzer.analyze(scan_result)

    assert "Express" in analysis.repo_info.frameworks
    assert "express" in analysis.repo_info.dependencies
