import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from app.analyzers.architecture import ArchitectureAnalyzer
from app.generators.diagram import DiagramGenerator
from app.models.architecture import ArchitectureGraph, ArchNode, ArchEdge
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


@pytest.fixture
def sample_scan_result():
    return ScanResult(
        repository_name="test-repo",
        commit_sha="abc123",
        total_files=10,
        total_lines=500,
        total_size_mb=1.0,
        files=[
            FileInfo(
                path="main.py",
                size_kb=5,
                lines=50,
                extension=".py",
                is_binary=False,
            )
        ],
        file_tree={},
    )


@pytest.fixture
def sample_project_analysis():
    return ProjectAnalysis(
        repo_info=RepoInfo(
            languages={".py": 80.0, ".js": 20.0},
            frameworks=["FastAPI", "React"],
            dependencies=["fastapi", "sqlalchemy", "pydantic"],
            entry_points=["main.py"],
        ),
        top_files=[
            RankedFile(path="main.py", score=100, reason="Entry point")
        ],
    )


@pytest.fixture
def sample_endpoints():
    return [
        Endpoint(
            method="GET",
            path="/users",
            file="routes.py",
            description="Fetch users",
        ),
        Endpoint(
            method="POST",
            path="/users",
            file="routes.py",
            description="Create user",
        ),
    ]


def test_architecture_analyzer_with_ollama_mock():
    analyzer = ArchitectureAnalyzer()

    with patch.object(
        analyzer.ollama_client,
        "generate_structured",
    ) as mock_generate:
        mock_generate.return_value = ArchitectureGraph(
            nodes=[
                ArchNode(
                    id="frontend",
                    label="React Frontend",
                    node_type="frontend",
                    description="Web UI",
                ),
                ArchNode(
                    id="backend",
                    label="FastAPI Backend",
                    node_type="backend",
                    description="REST API",
                ),
                ArchNode(
                    id="database",
                    label="PostgreSQL",
                    node_type="database",
                    description="User data",
                ),
            ],
            edges=[
                ArchEdge(
                    from_node="frontend",
                    to_node="backend",
                    label="HTTP",
                    edge_type="data",
                ),
                ArchEdge(
                    from_node="backend",
                    to_node="database",
                    label="SQL",
                    edge_type="data",
                ),
            ],
            title="System Architecture",
            description="Frontend to backend to database",
        )

        graph = analyzer.analyze(
            ScanResult(
                repository_name="test",
                commit_sha="abc",
                total_files=1,
                total_lines=1,
                total_size_mb=0.1,
                files=[],
                file_tree={},
            ),
            ProjectAnalysis(
                repo_info=RepoInfo(
                    languages={},
                    frameworks=["FastAPI"],
                    dependencies=[],
                    entry_points=[],
                ),
                top_files=[],
            ),
            [],
            DatabaseInfo(db_type="PostgreSQL"),
            AuthInfo(mechanism="JWT"),
            [],
        )

        assert len(graph.nodes) == 3
        assert len(graph.edges) == 2
        assert graph.title == "System Architecture"


def test_architecture_analyzer_fallback(
    sample_scan_result,
    sample_project_analysis,
    sample_endpoints,
):
    analyzer = ArchitectureAnalyzer()

    with patch.object(
        analyzer.ollama_client,
        "generate_structured",
    ) as mock_generate:
        mock_generate.side_effect = RuntimeError("Ollama unavailable")

        graph = analyzer.analyze(
            sample_scan_result,
            sample_project_analysis,
            sample_endpoints,
            DatabaseInfo(db_type="PostgreSQL", models=["User", "Post"]),
            AuthInfo(mechanism="JWT"),
            [],
        )

        assert graph.title == "System Architecture (Fallback)"
        node_types = {n.node_type for n in graph.nodes}
        assert "backend" in node_types
        assert "database" in node_types


def test_architecture_graph_validation():
    analyzer = ArchitectureAnalyzer()

    graph = ArchitectureGraph(
        nodes=[
            ArchNode(id="a", label="A", node_type="backend"),
            ArchNode(id="b", label="B", node_type="database"),
        ],
        edges=[
            ArchEdge(from_node="a", to_node="b", edge_type="data"),
            ArchEdge(from_node="invalid", to_node="b", edge_type="data"),
        ],
    )

    fixed = analyzer._validate_and_fix_graph(graph)
    assert len(fixed.edges) == 1
    assert fixed.edges[0].from_node == "a"


def test_diagram_generator_graphviz(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHVIZ_DOT", "dot")

    graph = ArchitectureGraph(
        nodes=[
            ArchNode(id="app", label="Application", node_type="backend"),
            ArchNode(id="db", label="Database", node_type="database"),
        ],
        edges=[
            ArchEdge(from_node="app", to_node="db", label="query", edge_type="data")
        ],
    )

    generator = DiagramGenerator(output_dir=str(tmp_path))
    results = generator.generate_all(graph, "test-repo")

    assert "mermaid" in results
    mermaid_file = results["mermaid"]
    assert (tmp_path / "architecture_test-repo.mmd").exists()


def test_diagram_generator_mermaid_format():
    graph = ArchitectureGraph(
        nodes=[
            ArchNode(id="web", label="Web", node_type="frontend"),
            ArchNode(id="api", label="API", node_type="backend"),
            ArchNode(id="pg", label="PostgreSQL", node_type="database"),
        ],
        edges=[
            ArchEdge(
                from_node="web",
                to_node="api",
                label="REST calls",
                edge_type="data",
            ),
            ArchEdge(
                from_node="api",
                to_node="pg",
                label="queries",
                edge_type="data",
            ),
        ],
    )

    generator = DiagramGenerator()
    mermaid = generator._generate_mermaid(graph, "myapp")

    if mermaid:
        content = mermaid.read_text(encoding="utf-8")
        assert "graph TB" in content
        assert "web" in content
        assert "api" in content
        assert "pg" in content


def test_diagram_generator_falls_back_without_graphviz(tmp_path, monkeypatch):
    from PIL import Image

    graph = ArchitectureGraph(
        title="Service <Architecture>",
        nodes=[
            ArchNode(
                id="api",
                label="API <Backend>",
                node_type="backend",
                description="Handles requests",
            ),
            ArchNode(id="db", label="PostgreSQL", node_type="database"),
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
    generator = DiagramGenerator(output_dir=str(tmp_path))
    monkeypatch.setattr(generator, "_generate_graphviz", lambda *args, **kwargs: None)

    results = generator.generate_all(graph, "fallback-test")

    assert set(results) == {"png", "svg", "mermaid"}
    with Image.open(results["png"]) as image:
        assert image.format == "PNG"
        assert image.width > 0 and image.height > 0
    svg = Path(results["svg"]).read_text(encoding="utf-8")
    assert "<svg " in svg
    assert "API &lt;Backend&gt;" in svg
