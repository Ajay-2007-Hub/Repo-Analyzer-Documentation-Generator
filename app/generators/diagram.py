import os
from pathlib import Path

import graphviz

from app.models.architecture import ArchitectureGraph


class DiagramGenerator:
    """Generate architecture diagrams from ArchitectureGraph using Graphviz."""

    NODE_COLORS = {
        "frontend": "#E8F4F8",
        "backend": "#F0E8F8",
        "database": "#F8F0E8",
        "auth": "#E8F8E8",
        "external": "#F8E8E8",
        "module": "#F8F8E8",
    }

    NODE_SHAPES = {
        "frontend": "box",
        "backend": "box",
        "database": "cylinder",
        "auth": "box",
        "external": "box",
        "module": "box",
    }

    def __init__(self, output_dir: str = "outputs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_all(
        self, graph: ArchitectureGraph, repo_name: str
    ) -> dict[str, str]:
        """
        Generate PNG, SVG, and Mermaid outputs.

        Returns:
            Dictionary with keys 'png', 'svg', 'mermaid' and output file paths.
        """
        results = {}

        png_path = self._generate_graphviz(graph, repo_name, format="png")
        if png_path:
            results["png"] = str(png_path)

        svg_path = self._generate_graphviz(graph, repo_name, format="svg")
        if svg_path:
            results["svg"] = str(svg_path)

        mermaid_path = self._generate_mermaid(graph, repo_name)
        if mermaid_path:
            results["mermaid"] = str(mermaid_path)

        return results

    def _generate_graphviz(
        self, graph: ArchitectureGraph, repo_name: str, format: str = "png"
    ) -> Path | None:  # noqa: A002
        """Generate diagram using Graphviz."""
        try:
            dot = graphviz.Digraph(
                name=f"{repo_name}_architecture",
                comment=graph.title or "Architecture Diagram",
                format=format,
                engine="dot",
            )

            dot.attr(rankdir="TB", bgcolor="white", fontname="Arial")
            dot.attr("node", fontname="Arial", fontsize="10")
            dot.attr("edge", fontname="Arial", fontsize="9")

            for node in graph.nodes:
                color = self.NODE_COLORS.get(node.node_type, "#FFFFFFFF")
                shape = self.NODE_SHAPES.get(node.node_type, "box")
                label = f"{node.label}\n({node.description})" if node.description else node.label
                dot.node(
                    node.id,
                    label,
                    shape=shape,
                    style="filled",
                    fillcolor=color,
                    penwidth="2",
                )

            for edge in graph.edges:
                label = edge.label or ""
                style = "solid"
                if edge.edge_type == "dependency":
                    style = "dashed"
                elif edge.edge_type == "control":
                    style = "dotted"

                dot.edge(
                    edge.from_node,
                    edge.to_node,
                    label=label,
                    style=style,
                    arrowsize="1.2",
                )

            safe_repo_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in repo_name)
            output_path = self.output_dir / f"architecture_{safe_repo_name}"
            dot.render(str(output_path), cleanup=True)

            result_path = output_path.with_suffix(f".{format}")
            if result_path.exists():
                return result_path
            return None

        except Exception as error:
            print(f"Graphviz error ({format}): {error}")
            return None

    def _generate_mermaid(
        self, graph: ArchitectureGraph, repo_name: str
    ) -> Path | None:
        """Generate Mermaid diagram syntax."""
        try:
            lines = ["graph TB"]

            for node in graph.nodes:
                mermaid_type = self._node_type_to_mermaid(node.node_type)
                line = f'    {node.id}{mermaid_type}["{node.label}"]'
                if node.description:
                    line = f'{line}\n    {node.id} -->|{node.description}| {node.id}'
                lines.append(line)

            for edge in graph.edges:
                arrow = "-->"
                if edge.edge_type == "dependency":
                    arrow = "-..->"
                elif edge.edge_type == "control":
                    arrow = "==> "

                if edge.label:
                    line = f'    {edge.from_node} -->|{edge.label}| {edge.to_node}'
                else:
                    line = f"    {edge.from_node} {arrow} {edge.to_node}"

                lines.append(line)

            mermaid_content = "\n".join(lines)

            safe_repo_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in repo_name)
            output_path = self.output_dir / f"architecture_{safe_repo_name}.mmd"

            output_path.write_text(mermaid_content, encoding="utf-8")
            return output_path

        except Exception as error:
            print(f"Mermaid generation error: {error}")
            return None

    @staticmethod
    def _node_type_to_mermaid(node_type: str) -> str:
        """Convert node type to Mermaid syntax."""
        mapping = {
            "frontend": "([",
            "backend": "[",
            "database": "[(", 
            "auth": "{",
            "external": "[[",
            "module": "[",
        }
        closing = {
            "frontend": "])",
            "backend": "]",
            "database": ")]",
            "auth": "}",
            "external": "]]",
            "module": "]",
        }
        return mapping.get(node_type, "[")
