import pytest
from app.core.cloner import Cloner
from app.core.scanner import Scanner
import os
import shutil

@pytest.fixture
def cloner():
    return Cloner(base_dir="tests/temp_repos")

@pytest.fixture
def scanner():
    return Scanner()

def test_url_validation(cloner):
    assert cloner.validate_url("https://github.com/owner/repo") is True
    assert cloner.validate_url("https://google.com") is False
    assert cloner.validate_url("ftp://github.com/owner/repo") is False

def test_clone_and_scan_integration(cloner, scanner):
    # Use a very small public repo for testing
    test_url = "https://github.com/psf/requests"

    try:
        repo_path = cloner.clone_repository(test_url)
        sha = cloner.get_commit_sha(repo_path)

        repo_name = test_url.split("/")[-1]
        result = scanner.scan(repo_path, repo_name, sha)

        assert result.repository_name == "requests"
        assert result.total_files > 0
        assert result.total_lines > 0
        assert result.commit_sha is not None

    finally:
        cloner.cleanup(repo_path if 'repo_path' in locals() else "")
        if os.path.exists("tests/temp_repos"):
            # Use the cloner's cleanup method instead of shutil.rmtree
            cloner.cleanup("tests/temp_repos")

def test_scanner_binary_detection(scanner, tmp_path):
    # Create a dummy binary file
    bin_file = tmp_path / "test.bin"
    bin_file.write_bytes(b"\x00\x01\x02\x03")

    assert scanner.is_binary(str(bin_file)) is True

    # Create a dummy text file
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("hello world")

    assert scanner.is_binary(str(txt_file)) is False
