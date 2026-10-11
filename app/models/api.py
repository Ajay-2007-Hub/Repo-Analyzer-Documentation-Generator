from pydantic import BaseModel, Field, field_validator


class AnalyzeRequest(BaseModel):
    repository_url: str = Field(
        ...,
        description="Public GitHub URL in https://github.com/<owner>/<repo> form",
    )

    @field_validator("repository_url")
    @classmethod
    def validate_github_url(cls, value: str) -> str:
        import re

        if not re.fullmatch(
            r"https://github\.com/[\w.-]+/[\w.-]+/?", value
        ):
            raise ValueError(
                "URL must be https://github.com/<owner>/<repo>."
            )
        return value.rstrip("/")


class AnalyzeResponse(BaseModel):
    id: str
    status: str
    progress: str
