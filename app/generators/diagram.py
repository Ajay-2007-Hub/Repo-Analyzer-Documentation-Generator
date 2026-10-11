import html
import logging
from pathlib import Path
from typing import ClassVar

import graphviz
from PIL import Image, ImageDraw, ImageFont

from app.models.architecture import ArchitectureGraph

logger = logging.getLogger(__name__)


class DiagramGenerator:
    """Generate architecture diagrams from ArchitectureGraph using Graphviz."""

    NODE_COLORS: ClassVar[dict[str, str]] = {
        "frontend": "#E8F4F8",
        "backend": "#F0E8F8",
        "database": "#F8F0E8",
        "auth": "#E8F8E8",
        "external": "#F8E8E8",
        "module": "#F8F8E8",
    }

    NODE_SHAPES: ClassVar[dict[str, str]] = {
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
        svg_path = self._generate_graphviz(graph, repo_name, format="svg")
        if png_path is None:
            logger.info("Graphviz PNG renderer unavailable; using built-in renderer.")
            png_path = self._generate_fallback_png(graph, repo_name)
        if svg_path is None:
            logger.info("Graphviz SVG renderer unavailable; using built-in renderer.")
            svg_path = self._generate_fallback_svg(graph, repo_name)
        results["png"] = str(png_path)
        results["svg"] = str(svg_path)

        mermaid_path = self._generate_mermaid(graph, repo_name)
        if mermaid_path:
            results["mermaid"] = str(mermaid_path)

        return results

    def _generate_graphviz(
        self, graph: ArchitectureGraph, repo_name: str, format: str = "png"
    ) -> Path | None:
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

        except (graphviz.backend.ExecutableNotFound, OSError) as error:
            logger.warning("Graphviz %s rendering unavailable: %s", format, error)
            return None
        except graphviz.backend.RenderError:
            logger.exception("Graphviz failed to render %s architecture.", format)
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
            logger.warning("Could not generate Mermaid architecture: %s", error)
            return None

    def _generate_fallback_svg(
        self, graph: ArchitectureGraph, repo_name: str
    ) -> Path:
        width, height, positions = self._layout(graph)
        safe_repo_name = self._safe_repo_name(repo_name)
        output_path = self.output_dir / f"architecture_{safe_repo_name}.svg"
        node_width, node_height = 290, 118
        elements = [
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
                f'height="{height}" viewBox="0 0 {width} {height}">'
            ),
            '<rect width="100%" height="100%" fill="#ffffff"/>',
            (
                '<defs><marker id="arrow" markerWidth="10" markerHeight="8" '
                'refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" '
                'fill="#526777"/></marker></defs>'
            ),
            (
                f'<text x="{width // 2}" y="42" text-anchor="middle" '
                'font-family="Arial,sans-serif" font-size="27" font-weight="700" '
                f'fill="#183b4e">{html.escape(graph.title or "Architecture")}</text>'
            ),
        ]
        for edge in graph.edges:
            if edge.from_node not in positions or edge.to_node not in positions:
                continue
            start, end = self._edge_points(
                positions[edge.from_node],
                positions[edge.to_node],
                node_width,
                node_height,
            )
            if start is None:
                continue
            elements.append(
                f'<line x1="{start[0]:.1f}" y1="{start[1]:.1f}" '
                f'x2="{end[0]:.1f}" y2="{end[1]:.1f}" stroke="#526777" '
                'stroke-width="2" marker-end="url(#arrow)"/>'
            )
            if edge.label:
                mid_x = (start[0] + end[0]) / 2
                mid_y = (start[1] + end[1]) / 2 - 8
                elements.append(
                    f'<text x="{mid_x:.1f}" y="{mid_y:.1f}" '
                    'text-anchor="middle" font-family="Arial,sans-serif" '
                    f'font-size="13" fill="#526777">{html.escape(edge.label)}</text>'
                )
        for node in graph.nodes:
            x, y = positions[node.id]
            color = self.NODE_COLORS.get(node.node_type, "#F8F8E8")
            elements.append(
                f'<rect x="{x}" y="{y}" width="{node_width}" '
                f'height="{node_height}" rx="12" fill="{color}" '
                'stroke="#526777" stroke-width="2"/>'
            )
            label_lines = self._wrap_text(node.label, 25, 2)
            first_y = y + 39 if node.description else y + 59
            elements.extend(
                f'<text x="{x + node_width // 2}" y="{first_y + index * 23}" '
                'text-anchor="middle" font-family="Arial,sans-serif" '
                f'font-size="18" font-weight="700" fill="#183b4e">'
                f'{html.escape(line)}</text>'
                for index, line in enumerate(label_lines)
            )
            if node.description:
                description_lines = self._wrap_text(node.description, 34, 2)
                elements.extend(
                    f'<text x="{x + node_width // 2}" '
                    f'y="{y + 82 + index * 17}" text-anchor="middle" '
                    'font-family="Arial,sans-serif" font-size="13" '
                    f'fill="#435866">{html.escape(line)}</text>'
                    for index, line in enumerate(description_lines)
                )
        elements.append("</svg>")
        output_path.write_text("\n".join(elements), encoding="utf-8")
        return output_path

    def _generate_fallback_png(
        self, graph: ArchitectureGraph, repo_name: str
    ) -> Path:
        width, height, positions = self._layout(graph)
        node_width, node_height = 290, 118
        image = Image.new("RGB", (width, height), "#ffffff")
        draw = ImageDraw.Draw(image)
        title_font = self._font(27)
        label_font = self._font(18)
        detail_font = self._font(13)
        edge_font = self._font(13)
        draw.text(
            (width // 2, 42),
            graph.title or "Architecture",
            fill="#183b4e",
            font=title_font,
            anchor="mm",
        )
        for edge in graph.edges:
            if edge.from_node not in positions or edge.to_node not in positions:
                continue
            start, end = self._edge_points(
                positions[edge.from_node],
                positions[edge.to_node],
                node_width,
                node_height,
            )
            if start is None:
                continue
            draw.line((start, end), fill="#526777", width=3)
            self._draw_arrowhead(draw, start, end)
            if edge.label:
                draw.text(
                    ((start[0] + end[0]) // 2, (start[1] + end[1]) // 2 - 10),
                    edge.label,
                    fill="#526777",
                    font=edge_font,
                    anchor="mm",
                )
        for node in graph.nodes:
            x, y = positions[node.id]
            draw.rounded_rectangle(
                (x, y, x + node_width, y + node_height),
                radius=12,
                fill=self.NODE_COLORS.get(node.node_type, "#F8F8E8"),
                outline="#526777",
                width=2,
            )
            label_lines = self._wrap_text(node.label, 25, 2)
            if node.description:
                label_y = y + 40
            else:
                label_y = y + 59
            draw.multiline_text(
                (x + node_width // 2, label_y),
                "\n".join(label_lines),
                fill="#183b4e",
                font=label_font,
                anchor="mm",
                align="center",
                spacing=2,
            )
            if node.description:
                draw.multiline_text(
                    (x + node_width // 2, y + 88),
                    "\n".join(self._wrap_text(node.description, 34, 2)),
                    fill="#435866",
                    font=detail_font,
                    anchor="mm",
                    align="center",
                    spacing=2,
                )
        output_path = (
            self.output_dir / f"architecture_{self._safe_repo_name(repo_name)}.png"
        )
        image.save(output_path, format="PNG")
        return output_path

    @staticmethod
    def _safe_repo_name(repo_name: str) -> str:
        return "".join(
            char if char.isalnum() or char in "-_" else "_"
            for char in repo_name
        )

    @staticmethod
    def _layout(
        graph: ArchitectureGraph,
    ) -> tuple[int, int, dict[str, tuple[int, int]]]:
        margin_x = 50
        margin_top = 92
        node_width = 290
        node_height = 118
        gap_x = 55
        gap_y = 74
        columns = 3
        rows = max(1, (len(graph.nodes) + columns - 1) // columns)
        width = margin_x * 2 + columns * node_width + (columns - 1) * gap_x
        height = margin_top + rows * node_height + (rows - 1) * gap_y + 45
        positions = {
            node.id: (
                margin_x + (index % columns) * (node_width + gap_x),
                margin_top + (index // columns) * (node_height + gap_y),
            )
            for index, node in enumerate(graph.nodes)
        }
        return width, height, positions

    @staticmethod
    def _edge_points(
        source: tuple[int, int],
        target: tuple[int, int],
        node_width: int,
        node_height: int,
    ) -> tuple[tuple[float, float] | None, tuple[float, float]]:
        source_center = (source[0] + node_width / 2, source[1] + node_height / 2)
        target_center = (target[0] + node_width / 2, target[1] + node_height / 2)
        dx = target_center[0] - source_center[0]
        dy = target_center[1] - source_center[1]
        if dx == 0 and dy == 0:
            return None, target_center
        scale = min(
            (node_width / 2) / abs(dx) if dx else float("inf"),
            (node_height / 2) / abs(dy) if dy else float("inf"),
        )
        return (
            (source_center[0] + dx * scale, source_center[1] + dy * scale),
            (target_center[0] - dx * scale, target_center[1] - dy * scale),
        )

    @staticmethod
    def _draw_arrowhead(
        draw: ImageDraw.ImageDraw,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = (dx * dx + dy * dy) ** 0.5
        if not length:
            return
        unit_x, unit_y = dx / length, dy / length
        base_x, base_y = end[0] - unit_x * 12, end[1] - unit_y * 12
        perpendicular_x, perpendicular_y = -unit_y * 6, unit_x * 6
        draw.polygon(
            [
                end,
                (base_x + perpendicular_x, base_y + perpendicular_y),
                (base_x - perpendicular_x, base_y - perpendicular_y),
            ],
            fill="#526777",
        )

    @staticmethod
    def _wrap_text(text: str, width: int, max_lines: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) > width and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip(" .") + "..."
        return lines or [""]

    @staticmethod
    def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        try:
            return ImageFont.truetype("arial.ttf", size)
        except OSError:
            return ImageFont.load_default(size=size)

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
        return mapping.get(node_type, "[")
