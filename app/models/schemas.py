from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class FileInfo(BaseModel):
    path: str
    size_kb: float
    lines: int
    extension: str
    is_binary: bool = False

class ScanResult(BaseModel):
    repository_name: str
    commit_sha: str
    total_files: int
    total_lines: int
    total_size_mb: float
    files: List[FileInfo]
    file_tree: Dict[str, Any]
    metadata: Dict[str, str] = Field(default_factory=dict)

class RankedFile(BaseModel):
    path: str
    score: int
    reason: str

class RepoInfo(BaseModel):
    languages: Dict[str, float] # extension -> percentage
    frameworks: List[str]
    dependencies: List[str]
    entry_points: List[str]
    readme_summary: Optional[str] = None

class ProjectAnalysis(BaseModel):
    repo_info: RepoInfo
    top_files: List[RankedFile]

class Endpoint(BaseModel):
    method: str
    path: str
    file: str
    description: str

class DatabaseInfo(BaseModel):
    db_type: str
    orm: Optional[str] = None
    models: List[str] = Field(default_factory=list)

class ExternalService(BaseModel):
    domain: str
    purpose: Optional[str] = "External API"

class AuthInfo(BaseModel):
    mechanism: str
    dependencies: List[str] = Field(default_factory=list)

class SecurityFinding(BaseModel):
    category: str
    severity: str
    file: str
    line: int
    description: str
