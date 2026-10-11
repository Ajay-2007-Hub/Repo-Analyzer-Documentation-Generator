import os
from typing import Optional

from app.llm.ollama_client import OllamaClient
from app.llm.context import ContextBuilder
from app.models.architecture import ArchitectureGraph
from app.models.schemas import (
    AuthInfo,
    DatabaseInfo,
    Endpoint,
    ExternalService,
    ProjectAnalysis,
    ScanResult,
    SecurityFinding,
)


class ArchitectureAnalyzer:
    """Analyzes repository context with Ollama to generate architecture diagrams."""

    def __init__(self):
        self.ollama_client = OllamaClient()

    def analyze(
        self,
        scan_result: ScanResult,
        project_analysis: ProjectAnalysis,
        endpoints: list[Endpoint],
        db_info: DatabaseInfo,
        auth_info: AuthInfo,
        security_findings: list[SecurityFinding],
        external_services: Optional[list[ExternalService]] = None,
    ) -> ArchitectureGraph:
        """
        Generate architecture graph using Ollama.

        Returns:
            ArchitectureGraph with nodes and edges validated by Pydantic.
        """
        context_builder = ContextBuilder(
            repo_path=".",
            token_budget=int(os.getenv("OLLAMA_NUM_CTX", "8192")) - 2048,
        )
        prompt = context_builder.build_context(
            scan_result,
            project_analysis,
            endpoints,
            db_info,
            auth_info,
            security_findings,
            external_services or [],
        )

        architecture_prompt = (
            prompt
            + "\n\n"
            "## ARCHITECTURE ANALYSIS TASK\n\n"
            "Analyze the provided repository and generate a system architecture diagram.\n\n"
            "Return a JSON object with:\n"
            "- `nodes`: list of architecture components (frontend, backend, database, auth, external, module)\n"
            "- `edges`: list of connections with types (data, control, dependency, calls)\n"
            "- `title`: short architecture title\n"
            "- `description`: 2-3 sentence high-level overview\n\n"
            "Constraints:\n"
            "1. Limit to 10-15 nodes (most important components only)\n"
            "2. Each node: id, label, node_type, description\n"
            "3. Each edge: from_node, to_node, label, edge_type\n"
            "4. Use only evidence from the provided context\n"
            "5. If architecture cannot be determined, return minimal nodes based on detected technologies\n"
        )

        try:
            graph = self.ollama_client.generate_structured(
                architecture_prompt, ArchitectureGraph, retries=2
            )
            graph = self._validate_and_fix_graph(graph)
            return graph
        except RuntimeError as error:
            return self._fallback_architecture(
                project_analysis, endpoints, db_info, auth_info, error
            )

    def _validate_and_fix_graph(self, graph: ArchitectureGraph) -> ArchitectureGraph:
        """Validate and fix architecture graph inconsistencies."""
        valid_nodes = set()
        for node in graph.nodes:
            valid_nodes.add(node.id)

        valid_edges = []
        for edge in graph.edges:
            if edge.from_node in valid_nodes and edge.to_node in valid_nodes:
                valid_edges.append(edge)

        graph.edges = valid_edges
        return graph

    def _fallback_architecture(
        self,
        project_analysis: ProjectAnalysis,
        endpoints: list[Endpoint],
        db_info: DatabaseInfo,
        auth_info: AuthInfo,
        error: Exception,
    ) -> ArchitectureGraph:
        """Generate a deterministic fallback architecture based on detected facts."""
        nodes = []
        edges = []

        if "frontend" in " ".join(project_analysis.repo_info.frameworks).lower():
            nodes.append(
                {"id": "frontend", "label": "Frontend", "node_type": "frontend", "description": "User Interface"}
            )

        if endpoints or any(
            fw in project_analysis.repo_info.frameworks
            for fw in ["FastAPI", "Flask", "Express", "Spring Boot"]
        ):
            nodes.append(
                {
                    "id": "backend",
                    "label": "Backend API",
                    "node_type": "backend",
                    "description": f"{len(endpoints)} endpoints detected",
                }
            )

        if db_info and db_info.db_type != "Not detected":
            nodes.append(
                {
                    "id": "database",
                    "label": f"{db_info.db_type}",
                    "node_type": "database",
                    "description": f"Database with {len(db_info.models)} models",
                }
            )

        if auth_info and auth_info.mechanism != "Not detected":
            nodes.append(
                {
                    "id": "auth",
                    "label": f"{auth_info.mechanism}",
                    "node_type": "auth",
                    "description": "Authentication Service",
                }
            )

        if nodes and "backend" in {n["id"] for n in nodes}:
            if "frontend" in {n["id"] for n in nodes}:
                edges.append(
                    {
                        "from_node": "frontend",
                        "to_node": "backend",
                        "label": "HTTP/REST",
                        "edge_type": "data",
                    }
                )

            if "database" in {n["id"] for n in nodes}:
                edges.append(
                    {
                        "from_node": "backend",
                        "to_node": "database",
                        "label": "SQL/ORM",
                        "edge_type": "data",
                    }
                )

            if "auth" in {n["id"] for n in nodes}:
                edges.append(
                    {
                        "from_node": "backend",
                        "to_node": "auth",
                        "label": "Verify",
                        "edge_type": "control",
                    }
                )

        return ArchitectureGraph(
            nodes=[ArchNode(**n) for n in nodes],
            edges=[ArchEdge(**e) for e in edges],
            title="System Architecture (Fallback)",
            description=f"Deterministic architecture based on {len(project_analysis.repo_info.frameworks)} detected frameworks",
        )


from app.models.architecture import ArchNode, ArchEdge
