from unittest.mock import Mock

import pytest
import requests

from frontend.app import (
    APIError,
    check_backend,
    check_ollama,
    fetch_download,
    fetch_results,
    normalize_api_url,
    poll_analysis,
    start_analysis,
)


def test_normalize_backend_url_and_reject_invalid_values():
    assert normalize_api_url(" http://localhost:8000/// ") == "http://localhost:8000"
    with pytest.raises(ValueError, match="must start"):
        normalize_api_url("localhost:8000")


def test_start_analysis_returns_run_and_surfaces_backend_validation():
    session = Mock()
    session.post.return_value = Mock(
        status_code=202,
        json=Mock(return_value={"id": "run-123", "status": "queued"}),
    )
    result = start_analysis(
        "http://localhost:8000",
        "https://github.com/example/repo",
        session=session,
    )
    assert result["id"] == "run-123"
    assert session.post.call_args.kwargs["json"]["repository_url"] == (
        "https://github.com/example/repo"
    )

    session.post.return_value = Mock(
        status_code=422,
        json=Mock(return_value={"detail": "Invalid GitHub URL"}),
    )
    with pytest.raises(APIError, match="Invalid GitHub URL"):
        start_analysis("http://localhost:8000", "bad-url", session=session)


def test_poll_analysis_reports_progress_and_terminal_failure():
    session = Mock()
    queued = Mock(status_code=200)
    queued.json.return_value = {
        "status": "running",
        "progress": "Scanning repository...",
    }
    complete = Mock(status_code=200)
    complete.json.return_value = {
        "status": "completed",
        "progress": "Analysis complete",
    }
    session.get.side_effect = [queued, complete]
    updates = []
    result = poll_analysis(
        "http://localhost:8000",
        "run-123",
        on_progress=lambda status, text: updates.append((status, text)),
        session=session,
        timeout_seconds=10,
        sleep=lambda _: None,
    )
    assert result["status"] == "completed"
    assert updates == [
        ("running", "Scanning repository..."),
        ("completed", "Analysis complete"),
    ]

    failed = Mock(status_code=200)
    failed.json.return_value = {
        "status": "failed",
        "error": "Repository not found",
    }
    session.get.side_effect = [failed]
    with pytest.raises(APIError, match="Repository not found"):
        poll_analysis(
            "http://localhost:8000",
            "run-123",
            session=session,
            timeout_seconds=1,
            sleep=lambda _: None,
        )


def test_poll_analysis_times_out_and_network_failures_are_visible(monkeypatch):
    session = Mock()
    session.get.side_effect = requests.ConnectionError("backend unavailable")
    with pytest.raises(APIError, match="backend unavailable"):
        poll_analysis("http://localhost:8000", "run-123", session=session)

    response = Mock(status_code=200)
    response.json.return_value = {"status": "running", "progress": "Working"}
    session.get.side_effect = [response]
    clock = iter([0.0, 2.0])
    monkeypatch.setattr("frontend.app.time.monotonic", lambda: next(clock))
    with pytest.raises(APIError, match="still running"):
        poll_analysis(
            "http://localhost:8000",
            "run-123",
            session=session,
            timeout_seconds=1,
            poll_interval=0,
            sleep=lambda _: None,
        )


def test_result_download_and_ollama_helpers():
    session = Mock()
    session.get.return_value = Mock(
        status_code=200,
        json=Mock(
            return_value={
                "run": {"id": "run-123", "status": "completed"},
                "analysis": {"scan": {"repository_name": "sample"}},
                "outputs": {},
            }
        ),
        content=b"pdf-bytes",
    )
    result = fetch_results("http://localhost:8000", "run-123", session=session)
    assert result["analysis"]["scan"]["repository_name"] == "sample"
    assert (
        fetch_download("http://localhost:8000", "run-123", "pdf", session=session)
        == b"pdf-bytes"
    )
    with pytest.raises(ValueError, match="Unsupported"):
        fetch_download("http://localhost:8000", "run-123", "exe", session=session)

    session.get.return_value = Mock(status_code=503)
    available, detail = check_ollama("http://localhost:11434", session=session)
    assert not available
    assert "503" in detail

    session.get.side_effect = requests.ConnectionError("offline")
    available, detail = check_ollama("http://localhost:11434", session=session)
    assert not available
    assert "offline" in detail


def test_backend_health_check_reports_unavailable():
    session = Mock()
    session.get.side_effect = requests.ConnectionError("backend offline")
    available, detail = check_backend("http://localhost:8000", session=session)
    assert not available
    assert "backend offline" in detail


def test_streamlit_home_renders_required_controls(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(
        requests,
        "get",
        Mock(side_effect=requests.ConnectionError("Ollama is offline")),
    )
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "frontend" / "app.py"
    app = AppTest.from_file(script, default_timeout=10).run()

    assert not app.exception
    assert app.title[0].value == "RepoInsight AI"
    assert any(item.label == "GitHub Repository URL" for item in app.text_input)
    assert any(item.label == "Analyze Repository" for item in app.button)
    assert any("Ollama is offline" in warning.value for warning in app.warning)
    assert any("backend is offline" in warning.value for warning in app.warning)
    assert any("Analyze Repository" in info.value for info in app.info)
