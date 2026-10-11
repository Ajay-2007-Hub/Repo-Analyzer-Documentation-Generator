from pydantic import BaseModel, Field


class ReportNarrative(BaseModel):
    problem_statement: str = "Not detected"
    objectives: list[str] = Field(default_factory=list)
    working_flow: list[str] = Field(default_factory=list)
    future_enhancements: list[str] = Field(default_factory=list)
