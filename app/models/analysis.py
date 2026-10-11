from pydantic import BaseModel, Field

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


class AnalysisDocument(BaseModel):
    scan: ScanResult
    project: ProjectAnalysis
    endpoints: list[Endpoint] = Field(default_factory=list)
    database: DatabaseInfo | None = None
    authentication: AuthInfo | None = None
    external_services: list[ExternalService] = Field(default_factory=list)
    security_findings: list[SecurityFinding] = Field(default_factory=list)
    architecture: ArchitectureGraph


class PipelineOutcome(BaseModel):
    commit_sha: str
    analysis: AnalysisDocument
    outputs: dict[str, str]
