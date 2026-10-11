import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SLIDE_TITLES = (
    "Title",
    "Project Overview",
    "Problem Statement",
    "Objectives",
    "Technology Stack",
    "Architecture",
    "API Endpoints",
    "System Workflow",
    "Main Modules",
    "Conclusion",
)

SlideTitle = Literal[
    "Title",
    "Project Overview",
    "Problem Statement",
    "Objectives",
    "Technology Stack",
    "Architecture",
    "API Endpoints",
    "System Workflow",
    "Main Modules",
    "Conclusion",
]


class PresentationSlide(BaseModel):
    title: SlideTitle
    bullets: list[str] = Field(min_length=3, max_length=5)

    @field_validator("bullets")
    @classmethod
    def validate_bullet_length(cls, bullets: list[str]) -> list[str]:
        for bullet in bullets:
            words = re.findall(r"\b[\w'-]+\b", bullet)
            if not bullet.strip():
                raise ValueError("Slide bullets must not be empty")
            if len(words) > 12:
                raise ValueError("Each slide bullet must contain at most 12 words")
        return bullets


class PresentationContent(BaseModel):
    slides: list[PresentationSlide] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def validate_slide_order(self):
        titles = tuple(slide.title for slide in self.slides)
        if titles != SLIDE_TITLES:
            raise ValueError("Slides must use the required 10 titles in order")
        return self
