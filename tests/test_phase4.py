import pytest
import os
from app.analyzers.database import DatabaseAnalyzer
from app.analyzers.external import ExternalAPIAnalyzer
from app.analyzers.security import SecurityAnalyzer
from app.models.schemas import ScanResult, FileInfo, ProjectAnalysis, RepoInfo

@pytest.fixture
def dummy_scan():
    return ScanResult(
        repository_name="test",
        commit_sha="123",
        total_files=2,
        total_lines=10,
        total_size_mb=0.1,
        files=[
            FileInfo(path=".env", size_kb=1, lines=1, extension=".env", is_binary=False),
            FileInfo(path="app.py", size_kb=1, lines=5, extension=".py", is_binary=False),
        ],
        file_tree={}
    )

@pytest.fixture
def dummy_analysis():
    return ProjectAnalysis(
        repo_info=RepoInfo(languages={}, frameworks=[], dependencies=['sqlalchemy', 'psycopg2'], entry_points=[]),
        top_files=[]
    )

def test_database_analyzer(tmp_path, dummy_scan, dummy_analysis):
    # Create a dummy .env with connection string
    (tmp_path / ".env").write_text("DATABASE_URL=postgres://user:pass@localhost/db")

    analyzer = DatabaseAnalyzer(str(tmp_path))
    result = analyzer.analyze(dummy_scan, dummy_analysis)

    assert result is not None
    assert result.db_type == "PostgreSQL"
    assert result.orm == "SQLAlchemy"

def test_external_api_analyzer(tmp_path, dummy_scan):
    # Create a file with external URL
    (tmp_path / "app.py").write_text("import requests\nrequests.get('https://api.stripe.com/v1/charges')")

    analyzer = ExternalAPIAnalyzer(str(tmp_path))
    services, auth = analyzer.analyze(dummy_scan)

    assert any(s.domain == "api.stripe.com" for s in services)

def test_security_analyzer(tmp_path):
    # Create a file with a secret
    (tmp_path / "config.py").write_text("API_KEY = 'AKIA1234567890ABCDEF'")
    (tmp_path / "app.py").write_text("DEBUG = True")

    # Create a .env file but no gitignore
    (tmp_path / ".env").write_text("SECRET=123")

    analyzer = SecurityAnalyzer(str(tmp_path))
    # Pass paths of files to scan
    findings = analyzer.analyze(["config.py", "app.py", ".env"], gitignore_content="")

    categories = [f.category for f in findings]
    assert "AWS Access Key" in categories
    assert "Configuration" in categories
    assert "Secret Exposure" in categories
