from pydantic import BaseModel, Field


class ArchNode(BaseModel):
    id: str = Field(..., description="Unique node identifier")
    label: str = Field(..., description="Display label")
    node_type: str = Field(
        ...,
        description="Node type: frontend, backend, database, auth, external, module",
    )
    description: str = Field(default="", description="Node description")


class ArchEdge(BaseModel):
    from_node: str = Field(..., description="Source node ID")
    to_node: str = Field(..., description="Target node ID")
    label: str = Field(default="", description="Edge label")
    edge_type: str = Field(
        default="data",
        description="Edge type: data, control, dependency, calls",
    )


class ArchitectureGraph(BaseModel):
    nodes: list[ArchNode] = Field(
        default_factory=list, description="Architecture nodes"
    )
    edges: list[ArchEdge] = Field(
        default_factory=list, description="Architecture edges"
    )
    title: str = Field(default="Architecture Diagram", description="Diagram title")
    description: str = Field(
        default="", description="High-level architecture description"
    )
