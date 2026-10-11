import re

from reportlab.platypus import LongTable

from app.generators.report import ReportGenerator
from app.models.architecture import ArchEdge, ArchitectureGraph, ArchNode
from app.models.report import ReportNarrative
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


def sample_inputs(endpoint_count: int = 0):
    scan_result = ScanResult(
        repository_name="sample-repo",
        commit_sha="abc123",
        total_files=3,
        total_lines=100,
        total_size_mb=0.5,
        files=[
            FileInfo(
                path="src/main.py",
                size_kb=2.5,
                lines=60,
                extension=".py",
                is_binary=False,
            ),
            FileInfo(
                path="README.md",
                size_kb=1.0,
                lines=25,
                extension=".md",
                is_binary=False,
            ),
            FileInfo(
                path="requirements.txt",
                size_kb=0.5,
                lines=15,
                extension=".txt",
                is_binary=False,
            ),
        ],
        file_tree={},
    )
    project_analysis = ProjectAnalysis(
        repo_info=RepoInfo(
            languages={"Python": 80.0, "Markdown": 20.0},
            frameworks=["FastAPI"],
            dependencies=["fastapi", "pydantic"],
            entry_points=["src/main.py"],
            readme_summary="A sample service.",
        ),
        top_files=[
            RankedFile(
                path="src/main.py", score=100, reason="Application entry point"
            )
        ],
    )
    endpoints = [
        Endpoint(
            method="GET" if index % 2 == 0 else "POST",
            path=f"/items/{index}",
            file=f"src/routes_{index % 4}.py",
            description=f"Read or create item number {index}.",
        )
        for index in range(endpoint_count)
    ]
    architecture = ArchitectureGraph(
        nodes=[
            ArchNode(
                id="api",
                label="FastAPI",
                node_type="backend",
                description="HTTP service",
            ),
            ArchNode(
                id="db",
                label="SQLite",
                node_type="database",
                description="Persistent data",
            ),
        ],
        edges=[
            ArchEdge(
                from_node="api",
                to_node="db",
                label="queries",
                edge_type="data",
            )
        ],
    )
    return scan_result, project_analysis, endpoints, architecture


def test_report_generates_pdf_with_zero_endpoints_and_architecture(tmp_path):
    scan, analysis, endpoints, architecture = sample_inputs()
    generator = ReportGenerator(tmp_path)

    destination = generator.generate(
        scan,
        analysis,
        endpoints,
        db_info=DatabaseInfo(db_type="SQLite", orm="SQLAlchemy"),
        auth_info=AuthInfo(mechanism="Not detected"),
        external_services=[ExternalService(domain="api.example.test")],
        security_findings=[
            SecurityFinding(
                category="Configuration",
                severity="MEDIUM",
                file="src/main.py",
                line=12,
                description="Debug mode is enabled",
            )
        ],
        architecture=architecture,
        narrative=ReportNarrative(
            problem_statement="Validated narrative from repository evidence.",
            objectives=["Serve item requests"],
            working_flow=["HTTP request", "FastAPI handler", "SQLite query"],
            future_enhancements=["Add request tracing"],
        ),
    )

    pdf = destination.read_bytes()
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 3000
    assert destination.name == "sample-repo_report.pdf"

    story = generator._build_story(
        scan_result=scan,
        project_analysis=analysis,
        endpoints=endpoints,
        db_info=None,
        auth_info=None,
        external_services=[],
        security_findings=[],
        architecture=architecture,
        diagram_path=None,
        narrative=None,
    )
    section_titles = [
        flowable.getPlainText()
        for flowable in story
        if getattr(getattr(flowable, "style", None), "name", None)
        == "ReportHeading1"
    ]
    assert section_titles == [
        "1. Project Overview",
        "2. Problem Statement",
        "3. Objectives",
        "4. Technology Stack",
        "5. Repository Structure",
        "6. Architecture",
        "7. API Endpoints",
        "8. Database",
        "9. Main Modules",
        "10. Working Flow",
        "11. Security Observations",
        "12. Dependencies",
        "13. Future Enhancements",
    ]
    assert any(
        getattr(flowable, "getPlainText", lambda: "")() == "No API endpoints detected."
        for flowable in story
    )
    assert any(flowable.__class__.__name__ == "_ArchitectureDiagram" for flowable in story)


def test_report_keeps_100_plus_endpoint_table_paginated(tmp_path):
    scan, analysis, endpoints, architecture = sample_inputs(endpoint_count=125)
    generator = ReportGenerator(tmp_path)
    story = generator._build_story(
        scan_result=scan,
        project_analysis=analysis,
        endpoints=endpoints,
        db_info=DatabaseInfo(db_type="PostgreSQL"),
        auth_info=None,
        external_services=[],
        security_findings=[],
        architecture=architecture,
        diagram_path=None,
        narrative=None,
    )

    endpoint_table = next(
        flowable
        for flowable in story
        if isinstance(flowable, LongTable)
        and len(flowable._cellvalues) == len(endpoints) + 1
    )
    assert endpoint_table.repeatRows == 1
    assert len(endpoint_table._cellvalues) == 126
    assert generator.generate(
        scan,
        analysis,
        endpoints,
        db_info=DatabaseInfo(db_type="PostgreSQL"),
        architecture=architecture,
    ).read_bytes().startswith(b"%PDF-")

    page_objects = re.findall(rb"/Type\s*/Page\b(?!s)", (tmp_path / "sample-repo_report.pdf").read_bytes())
    assert len(page_objects) >= 4


def test_report_escapes_repository_content_and_rejects_missing_diagram(tmp_path):
    scan, analysis, endpoints, architecture = sample_inputs()
    scan.repository_name = "sample <script> repo"
    generator = ReportGenerator(tmp_path)
    story = generator._build_story(
        scan_result=scan,
        project_analysis=analysis,
        endpoints=endpoints,
        db_info=None,
        auth_info=None,
        external_services=[],
        security_findings=[],
        architecture=architecture,
        diagram_path=None,
        narrative=None,
    )
    cover = next(
        flowable
        for flowable in story
        if getattr(flowable, "getPlainText", lambda: "")() == "sample <script> repo"
    )
    assert "&lt;script&gt;" in cover.text

    try:
        generator.generate(
            scan,
            analysis,
            endpoints,
            architecture=architecture,
            diagram_path=tmp_path / "missing.png",
        )
    except FileNotFoundError as error:
        assert "Architecture diagram not found" in str(error)
    else:
        raise AssertionError("A supplied but missing diagram should be reported")
