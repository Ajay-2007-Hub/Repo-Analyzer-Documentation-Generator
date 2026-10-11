# RepoInsight AI

RepoInsight AI is a Python-based system that automatically analyzes public GitHub repositories to generate architecture diagrams, detailed project reports, PowerPoint presentations, and structured JSON analysis.

## Features
- Clone and scan public GitHub repositories.
- Detect languages, frameworks, and dependencies.
- Analyze API endpoints (FastAPI, Flask, Express, Spring Boot).
- Detect databases, authentication, and external API usage.
- Generate architecture diagrams via Graphviz.
- Generate professional PDF reports and PPT presentations using local LLMs (Ollama).

## Technology Stack
- **Frontend**: Streamlit
- **Backend**: FastAPI
- **LLM**: Ollama (Qwen3-Coder)
- **Analysis**: GitPython, Python `ast`, Tree-sitter
- **Generation**: Graphviz, ReportLab, python-pptx
- **Database**: SQLite
- **Validation**: Pydantic
- **Quality**: Pytest, Ruff
