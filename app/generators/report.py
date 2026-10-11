import math
import re
from pathlib import Path
from typing import Any, ClassVar
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    LongTable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from app.models.architecture import ArchitectureGraph
from app.models.report import ReportNarrative
from app.models.schemas import (
    AuthInfo,
    DatabaseInfo,
    Endpoint,
    ExternalService,
    ProjectAnalysis,
    ScanResult,
    SecurityFinding,
)

PAGE_WIDTH, PAGE_HEIGHT = letter
LEFT_MARGIN = RIGHT_MARGIN = 0.62 * inch
TOP_MARGIN = 0.72 * inch
BOTTOM_MARGIN = 0.62 * inch
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN


class _ReportDocument(BaseDocTemplate):
    def __init__(self, target: Any, title: str, styles: dict[str, ParagraphStyle]):
        super().__init__(
            target,
            pagesize=letter,
            leftMargin=LEFT_MARGIN,
            rightMargin=RIGHT_MARGIN,
            topMargin=TOP_MARGIN,
            bottomMargin=BOTTOM_MARGIN,
            title=title,
            author="RepoInsight AI",
            subject="Repository analysis report",
        )
        self.heading_style_name = styles["Heading1"].name
        frame = Frame(
            LEFT_MARGIN,
            BOTTOM_MARGIN,
            CONTENT_WIDTH,
            PAGE_HEIGHT - TOP_MARGIN - BOTTOM_MARGIN,
            id="main",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(
            PageTemplate(id="report", frames=[frame], onPage=self._draw_page_chrome)
        )

    def afterFlowable(self, flowable: Flowable) -> None:
        if (
            isinstance(flowable, Paragraph)
            and flowable.style.name == self.heading_style_name
        ):
            text = flowable.getPlainText()
            self.notify("TOCEntry", (0, text, self.page))

    @staticmethod
    def _draw_page_chrome(canvas, doc) -> None:
        if doc.page == 1:
            return
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D7E0E8"))
        canvas.setLineWidth(0.5)
        canvas.line(LEFT_MARGIN, PAGE_HEIGHT - 0.48 * inch, PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 0.48 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#526477"))
        canvas.drawString(LEFT_MARGIN, PAGE_HEIGHT - 0.38 * inch, "RepoInsight AI | Repository Analysis")
        canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, 0.36 * inch, f"Page {doc.page}")
        canvas.restoreState()


class _ArchitectureDiagram(Flowable):
    """Draw a compact PDF-native architecture diagram when no PNG is supplied."""

    PALETTE: ClassVar[dict[str, str]] = {
        "frontend": "#E8F4F8",
        "backend": "#F0E8F8",
        "database": "#F8F0E8",
        "auth": "#E8F8E8",
        "external": "#F8E8E8",
        "module": "#F8F8E8",
    }

    def __init__(self, graph: ArchitectureGraph, width: float = CONTENT_WIDTH):
        super().__init__()
        self.graph = graph
        self.width = width
        self.visible_nodes = graph.nodes[:12]
        self.node_rows = math.ceil(len(self.visible_nodes) / 3) if self.visible_nodes else 1
        self.height = max(1, self.node_rows) * 0.9 * inch
        self._node_positions: dict[str, tuple[float, float]] = {}

    def draw(self) -> None:
        canvas = self.canv
        columns = 3
        cell_width = self.width / columns
        cell_height = self.height / self.node_rows
        box_width = cell_width * 0.82
        box_height = min(0.56 * inch, cell_height * 0.72)
        nodes_by_id = {}

        for index, node in enumerate(self.visible_nodes):
            row, column = divmod(index, columns)
            center_x = column * cell_width + cell_width / 2
            center_y = self.height - row * cell_height - cell_height / 2
            self._node_positions[node.id] = (center_x, center_y)
            nodes_by_id[node.id] = node

        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#718096"))
        canvas.setFillColor(colors.HexColor("#718096"))
        for edge in self.graph.edges:
            if (
                edge.from_node not in self._node_positions
                or edge.to_node not in self._node_positions
                or edge.from_node == edge.to_node
            ):
                continue
            start_x, start_y = self._node_positions[edge.from_node]
            end_x, end_y = self._node_positions[edge.to_node]
            dx, dy = end_x - start_x, end_y - start_y
            distance = math.hypot(dx, dy) or 1
            inset_x = (box_width / 2 + 3) * dx / distance
            inset_y = (box_height / 2 + 3) * dy / distance
            x1, y1 = start_x + inset_x, start_y - inset_y
            x2, y2 = end_x - inset_x, end_y - inset_y
            canvas.setDash(3, 2) if edge.edge_type == "dependency" else canvas.setDash()
            canvas.line(x1, y1, x2, y2)
            angle = math.atan2(y2 - y1, x2 - x1)
            arrow_length = 5
            canvas.line(
                x2,
                y2,
                x2 - arrow_length * math.cos(angle - 0.45),
                y2 - arrow_length * math.sin(angle - 0.45),
            )
            canvas.line(
                x2,
                y2,
                x2 - arrow_length * math.cos(angle + 0.45),
                y2 - arrow_length * math.sin(angle + 0.45),
            )
            if edge.label:
                canvas.setFont("Helvetica", 6)
                canvas.drawCentredString(
                    (x1 + x2) / 2,
                    (y1 + y2) / 2 + 3,
                    _pdf_safe_text(edge.label[:28]),
                )

        for node_id, node in nodes_by_id.items():
            center_x, center_y = self._node_positions[node_id]
            x = center_x - box_width / 2
            y = center_y - box_height / 2
            canvas.setDash()
            canvas.setFillColor(colors.HexColor(self.PALETTE.get(node.node_type, "#F8F8F8")))
            canvas.setStrokeColor(colors.HexColor("#557086"))
            canvas.roundRect(x, y, box_width, box_height, 5, fill=1, stroke=1)
            label_lines = simpleSplit(
                _pdf_safe_text(node.label), "Helvetica-Bold", 8, box_width - 10
            )[:2]
            description_lines = simpleSplit(
                _pdf_safe_text(node.description or node.node_type),
                "Helvetica",
                6.5,
                box_width - 10,
            )[:2]
            total_height = len(label_lines) * 9 + len(description_lines) * 8
            text_y = center_y + total_height / 2 - 8
            canvas.setFillColor(colors.HexColor("#233746"))
            canvas.setFont("Helvetica-Bold", 8)
            for line in label_lines:
                canvas.drawCentredString(center_x, text_y, line)
                text_y -= 9
            canvas.setFont("Helvetica", 6.5)
            canvas.setFillColor(colors.HexColor("#526477"))
            for line in description_lines:
                canvas.drawCentredString(center_x, text_y, line)
                text_y -= 8

        canvas.restoreState()


class ReportGenerator:
    """Generate a factual, paginated PDF repository analysis report."""

    def __init__(self, output_dir: str | Path = "outputs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.styles = self._make_styles()

    def generate(
        self,
        scan_result: ScanResult,
        project_analysis: ProjectAnalysis,
        endpoints: list[Endpoint],
        db_info: DatabaseInfo | None = None,
        auth_info: AuthInfo | None = None,
        external_services: list[ExternalService] | None = None,
        security_findings: list[SecurityFinding] | None = None,
        architecture: ArchitectureGraph | None = None,
        diagram_path: str | Path | None = None,
        narrative: ReportNarrative | None = None,
        output_path: str | Path | None = None,
    ) -> Path:
        """Create a PDF report and return its path."""
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", scan_result.repository_name).strip("_")
        destination = (
            Path(output_path)
            if output_path is not None
            else self.output_dir / f"{safe_name or 'repository'}_report.pdf"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        document = _ReportDocument(
            str(destination),
            f"RepoInsight AI Report — {scan_result.repository_name}",
            self.styles,
        )
        story = self._build_story(
            scan_result=scan_result,
            project_analysis=project_analysis,
            endpoints=endpoints,
            db_info=db_info,
            auth_info=auth_info,
            external_services=external_services or [],
            security_findings=security_findings or [],
            architecture=architecture,
            diagram_path=diagram_path,
            narrative=narrative,
        )
        document.multiBuild(story)
        return destination

    def _build_story(
        self,
        *,
        scan_result: ScanResult,
        project_analysis: ProjectAnalysis,
        endpoints: list[Endpoint],
        db_info: DatabaseInfo | None,
        auth_info: AuthInfo | None,
        external_services: list[ExternalService],
        security_findings: list[SecurityFinding],
        architecture: ArchitectureGraph | None,
        diagram_path: str | Path | None,
        narrative: ReportNarrative | None,
    ) -> list[Flowable]:
        story: list[Flowable] = []
        styles = self.styles
        repo_name = scan_result.repository_name

        story.extend(
            [
                Spacer(1, 1.3 * inch),
                self._paragraph("REPOINSIGHT AI", styles["Kicker"]),
                Spacer(1, 0.18 * inch),
                self._paragraph("Project Analysis Report", styles["CoverTitle"]),
                self._paragraph(repo_name, styles["CoverRepository"]),
                Spacer(1, 0.35 * inch),
                self._paragraph(
                    "A deterministic analysis of repository metadata, technologies, "
                    "interfaces, and architecture evidence.",
                    styles["CoverBody"],
                ),
                Spacer(1, 0.45 * inch),
                self._paragraph(
                    f"Commit: {scan_result.commit_sha or 'Not detected'}",
                    styles["CoverMeta"],
                ),
                self._paragraph(
                    f"Files scanned: {scan_result.total_files:,}  |  "
                    f"Lines: {scan_result.total_lines:,}  |  "
                    f"Repository size: {scan_result.total_size_mb:.2f} MB",
                    styles["CoverMeta"],
                ),
                PageBreak(),
                self._paragraph("Table of Contents", styles["TOCTitle"]),
            ]
        )
        toc = TableOfContents()
        toc.levelStyles = [
            ParagraphStyle(
                "TOCLevel1",
                parent=styles["Body"],
                leftIndent=0,
                firstLineIndent=0,
                leading=17,
                spaceBefore=4,
                textColor=colors.HexColor("#253B4A"),
            )
        ]
        toc.dotsMinLevel = 0
        story.extend([toc, PageBreak()])

        sections = [
            (
                "1. Project Overview",
                [
                    f"Repository: {repo_name}",
                    f"Commit: {scan_result.commit_sha or 'Not detected'}",
                    f"Files scanned: {scan_result.total_files:,}",
                    f"Total lines: {scan_result.total_lines:,}",
                    f"Repository size: {scan_result.total_size_mb:.2f} MB",
                ],
                project_analysis.repo_info.readme_summary or "Not detected",
            ),
            (
                "2. Problem Statement",
                [],
                narrative.problem_statement
                if narrative and narrative.problem_statement.strip()
                else "Not detected. A problem statement cannot be established from the available static repository facts.",
            ),
            (
                "3. Objectives",
                narrative.objectives if narrative else [],
                "No objectives were provided as validated repository interpretation."
                if not narrative or not narrative.objectives
                else None,
            ),
        ]
        for heading, bullets, paragraph in sections:
            self._add_section(story, heading)
            if paragraph:
                story.append(self._paragraph(paragraph, styles["Body"]))
            if bullets:
                self._add_bullets(story, bullets)
            if heading == "1. Project Overview":
                self._add_scan_summary_table(story, scan_result)

        self._add_section(story, "4. Technology Stack")
        self._add_technology_table(story, project_analysis)

        self._add_section(story, "5. Repository Structure")
        self._add_repository_structure(story, scan_result)

        self._add_section(story, "6. Architecture")
        self._add_architecture(story, architecture, diagram_path)

        self._add_section(story, "7. API Endpoints")
        self._add_endpoint_table(story, endpoints)

        self._add_section(story, "8. Database")
        self._add_database(story, db_info)

        self._add_section(story, "9. Main Modules")
        self._add_modules(story, project_analysis)

        self._add_section(story, "10. Working Flow")
        if narrative and narrative.working_flow:
            self._add_bullets(story, narrative.working_flow)
        else:
            entry_points = project_analysis.repo_info.entry_points
            if entry_points:
                story.append(
                    self._paragraph(
                        "Detected entry points: " + ", ".join(entry_points),
                        styles["Body"],
                    )
                )
            story.append(
                self._paragraph(
                    "Runtime request and data flow: Not detected from static analysis.",
                    styles["Body"],
                )
            )

        self._add_section(story, "11. Security Observations")
        self._add_security(story, auth_info, external_services, security_findings)

        self._add_section(story, "12. Dependencies")
        dependencies = project_analysis.repo_info.dependencies
        if dependencies:
            self._add_bullets(story, sorted(set(dependencies)))
        else:
            story.append(self._paragraph("Not detected.", styles["Body"]))

        self._add_section(story, "13. Future Enhancements")
        if narrative and narrative.future_enhancements:
            self._add_bullets(story, narrative.future_enhancements)
        else:
            story.append(
                self._paragraph(
                    "Not detected. No future-enhancement claims were inferred from repository facts.",
                    styles["Body"],
                )
            )
        return story

    def _add_scan_summary_table(self, story: list[Flowable], scan: ScanResult) -> None:
        rows = [
            ["Measure", "Detected value"],
            ["Files", f"{scan.total_files:,}"],
            ["Lines", f"{scan.total_lines:,}"],
            ["Repository size", f"{scan.total_size_mb:.2f} MB"],
        ]
        story.append(self._table(rows, [2.0 * inch, 4.8 * inch]))

    def _add_technology_table(
        self, story: list[Flowable], analysis: ProjectAnalysis
    ) -> None:
        info = analysis.repo_info
        rows = [["Category", "Detected evidence"]]
        rows.extend(
            ["Language", f"{name}: {percentage:.1f}%"]
            for name, percentage in sorted(
                info.languages.items(), key=lambda item: item[1], reverse=True
            )
        )
        rows.extend(["Framework", framework] for framework in sorted(info.frameworks))
        if len(rows) == 1:
            rows.append(["Technology", "Not detected"])
        story.append(self._table(rows, [1.6 * inch, 5.2 * inch]))

    def _add_repository_structure(
        self, story: list[Flowable], scan: ScanResult
    ) -> None:
        paths = sorted(file.path for file in scan.files)
        if not paths:
            story.append(self._paragraph("No files detected.", self.styles["Body"]))
            return
        rows: list[list[str]] = [["Path", "Lines", "Size (KB)"]]
        by_path = {file.path: file for file in scan.files}
        display_paths = paths[:120]
        for path in display_paths:
            file = by_path[path]
            rows.append([path, f"{file.lines:,}", f"{file.size_kb:.1f}"])
        if len(paths) > len(display_paths):
            rows.append(
                [
                    f"{len(paths) - len(display_paths)} additional files omitted",
                    "",
                    "",
                ]
            )
        story.append(
            self._table(
                rows,
                [4.5 * inch, 1.0 * inch, 1.3 * inch],
                long_table=True,
            )
        )

    def _add_architecture(
        self,
        story: list[Flowable],
        architecture: ArchitectureGraph | None,
        diagram_path: str | Path | None,
    ) -> None:
        if diagram_path is not None:
            image_path = Path(diagram_path)
            if not image_path.is_file():
                raise FileNotFoundError(f"Architecture diagram not found: {image_path}")
            if image_path.suffix.lower() == ".svg":
                raise ValueError("PDF embedding requires a raster architecture image, such as PNG.")
            image = Image(str(image_path))
            reader = ImageReader(str(image_path))
            image_width, image_height = reader.getSize()
            scale = min(6.7 * inch / image_width, 4.2 * inch / image_height)
            image.drawWidth = image_width * scale
            image.drawHeight = image_height * scale
            image.hAlign = "CENTER"
            story.extend([image, Spacer(1, 0.12 * inch)])
        elif architecture and architecture.nodes:
            story.extend(
                [
                    self._paragraph(architecture.title, self.styles["Subheading"]),
                    _ArchitectureDiagram(architecture),
                ]
            )
        else:
            story.append(
                self._paragraph(
                    "Architecture diagram not detected. The architecture analysis "
                    "did not provide components to visualize.",
                    self.styles["Body"],
                )
            )

        if architecture:
            if architecture.description:
                story.append(self._paragraph(architecture.description, self.styles["Body"]))
            if architecture.nodes:
                rows = [["Component", "Type", "Description"]]
                rows.extend(
                    [node.label, node.node_type, node.description or "Not detected"]
                    for node in architecture.nodes
                )
                story.append(self._table(rows, [1.75 * inch, 1.0 * inch, 4.05 * inch]))
            if architecture.edges:
                rows = [["Connection", "Relationship"]]
                rows.extend(
                    [
                        f"{edge.from_node} -> {edge.to_node}",
                        edge.label or edge.edge_type,
                    ]
                    for edge in architecture.edges
                )
                story.append(self._table(rows, [3.4 * inch, 3.4 * inch]))

    def _add_endpoint_table(
        self, story: list[Flowable], endpoints: list[Endpoint]
    ) -> None:
        if not endpoints:
            story.append(self._paragraph("No API endpoints detected.", self.styles["Body"]))
            return
        rows = [["Method", "Endpoint", "File", "Description"]]
        rows.extend(
            [endpoint.method, endpoint.path, endpoint.file, endpoint.description]
            for endpoint in sorted(
                endpoints,
                key=lambda item: (item.path, item.method, item.file),
            )
        )
        story.append(
            self._table(
                rows,
                [0.72 * inch, 1.35 * inch, 1.72 * inch, 2.96 * inch],
                long_table=True,
            )
        )

    def _add_database(
        self, story: list[Flowable], db_info: DatabaseInfo | None
    ) -> None:
        if not db_info:
            story.append(self._paragraph("Database: Not detected.", self.styles["Body"]))
            return
        rows = [
            ["Property", "Detected value"],
            ["Database", db_info.db_type or "Not detected"],
            ["ORM", db_info.orm or "Not detected"],
            ["Models", ", ".join(db_info.models) if db_info.models else "Not detected"],
        ]
        story.append(self._table(rows, [1.6 * inch, 5.2 * inch]))

    def _add_modules(
        self, story: list[Flowable], analysis: ProjectAnalysis
    ) -> None:
        if not analysis.top_files:
            story.append(self._paragraph("No ranked modules detected.", self.styles["Body"]))
            return
        rows = [["File", "Analysis"]]
        rows.extend(
            [ranked.path, ranked.reason or "Important source file"]
            for ranked in analysis.top_files[:10]
        )
        story.append(self._table(rows, [3.0 * inch, 3.8 * inch]))

    def _add_security(
        self,
        story: list[Flowable],
        auth_info: AuthInfo | None,
        external_services: list[ExternalService],
        findings: list[SecurityFinding],
    ) -> None:
        if auth_info:
            story.append(
                self._paragraph(
                    f"Authentication detected: {auth_info.mechanism}. Dependencies: "
                    f"{', '.join(auth_info.dependencies) or 'Not detected'}.",
                    self.styles["Body"],
                )
            )
        else:
            story.append(
                self._paragraph("Authentication: Not detected.", self.styles["Body"])
            )

        if external_services:
            story.append(self._paragraph("External service domains:", self.styles["Subheading"]))
            self._add_bullets(
                story,
                sorted(
                    {
                        f"{service.domain} — {service.purpose or 'Purpose not detected'}"
                        for service in external_services
                    }
                ),
            )
        else:
            story.append(
                self._paragraph("External services: Not detected.", self.styles["Body"])
            )

        if not findings:
            story.append(
                self._paragraph(
                    "No rule-based security findings were detected. This is not a security certification.",
                    self.styles["Body"],
                )
            )
            return
        rows = [["Severity", "Finding", "Location"]]
        rows.extend(
            [
                finding.severity,
                f"{finding.category}: {finding.description}",
                f"{finding.file}:{finding.line}",
            ]
            for finding in findings
        )
        story.append(
            self._table(
                rows,
                [0.9 * inch, 4.25 * inch, 1.65 * inch],
                long_table=True,
            )
        )

    def _add_bullets(self, story: list[Flowable], items: list[str]) -> None:
        for item in items:
            text = escape(_pdf_safe_text(item)).replace("\r\n", "\n").replace("\n", "<br/>")
            story.append(
                Paragraph(text, self.styles["Bullet"], bulletText=_pdf_safe_text("•"))
            )

    def _add_section(self, story: list[Flowable], title: str) -> None:
        story.extend([Spacer(1, 0.12 * inch), self._paragraph(title, self.styles["Heading1"])])

    def _table(
        self,
        rows: list[list[str]],
        widths: list[float],
        long_table: bool = False,
    ) -> Flowable:
        data = [
            [self._paragraph(cell, self.styles["TableHeader"] if row_index == 0 else self.styles["TableCell"])
             for cell in row]
            for row_index, row in enumerate(rows)
        ]
        table_type = LongTable if long_table else Table
        table = table_type(
            data,
            colWidths=widths,
            repeatRows=1,
            hAlign="LEFT",
            splitByRow=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F5368")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6F8")]),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D6E0E6")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return table

    @staticmethod
    def _paragraph(text: Any, style: ParagraphStyle) -> Paragraph:
        safe = escape(_pdf_safe_text(text))
        safe = safe.replace("\r\n", "\n").replace("\n", "<br/>")
        return Paragraph(safe, style)

    @staticmethod
    def _make_styles() -> dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()
        return {
            "Body": ParagraphStyle(
                "ReportBody",
                parent=base["BodyText"],
                fontName="Helvetica",
                fontSize=9,
                leading=13,
                textColor=colors.HexColor("#34495A"),
                spaceAfter=7,
                splitLongWords=1,
            ),
            "Bullet": ParagraphStyle(
                "ReportBullet",
                parent=base["BodyText"],
                fontName="Helvetica",
                fontSize=9,
                leading=13,
                leftIndent=11,
                firstLineIndent=-9,
                textColor=colors.HexColor("#34495A"),
                spaceAfter=3,
                splitLongWords=1,
            ),
            "Heading1": ParagraphStyle(
                "ReportHeading1",
                parent=base["Heading1"],
                fontName="Helvetica-Bold",
                fontSize=15,
                leading=19,
                textColor=colors.HexColor("#1F5368"),
                keepWithNext=True,
                spaceBefore=10,
                spaceAfter=9,
            ),
            "Subheading": ParagraphStyle(
                "ReportSubheading",
                parent=base["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=10,
                leading=13,
                textColor=colors.HexColor("#1F5368"),
                spaceBefore=6,
                spaceAfter=5,
            ),
            "TableCell": ParagraphStyle(
                "ReportTableCell",
                parent=base["BodyText"],
                fontName="Helvetica",
                fontSize=7.5,
                leading=9.5,
                textColor=colors.HexColor("#253B4A"),
                splitLongWords=1,
            ),
            "TableHeader": ParagraphStyle(
                "ReportTableHeader",
                parent=base["BodyText"],
                fontName="Helvetica-Bold",
                fontSize=7.5,
                leading=9.5,
                textColor=colors.white,
                splitLongWords=1,
            ),
            "Kicker": ParagraphStyle(
                "ReportKicker",
                fontName="Helvetica-Bold",
                fontSize=11,
                leading=14,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#138A8A"),
                tracking=1.5,
            ),
            "CoverTitle": ParagraphStyle(
                "ReportCoverTitle",
                fontName="Helvetica-Bold",
                fontSize=29,
                leading=35,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#183B4E"),
            ),
            "CoverRepository": ParagraphStyle(
                "ReportCoverRepository",
                fontName="Helvetica",
                fontSize=19,
                leading=25,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#138A8A"),
                spaceBefore=9,
            ),
            "CoverBody": ParagraphStyle(
                "ReportCoverBody",
                fontName="Helvetica",
                fontSize=11,
                leading=17,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#526477"),
            ),
            "CoverMeta": ParagraphStyle(
                "ReportCoverMeta",
                fontName="Helvetica",
                fontSize=9,
                leading=14,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#526477"),
            ),
            "TOCTitle": ParagraphStyle(
                "ReportTOCTitle",
                fontName="Helvetica-Bold",
                fontSize=20,
                leading=25,
                textColor=colors.HexColor("#183B4E"),
                spaceAfter=16,
            ),
        }


def _pdf_safe_text(value: Any) -> str:
    """Replace characters unsupported by ReportLab's built-in WinAnsi fonts."""
    return str(value).encode("cp1252", errors="replace").decode("cp1252")
