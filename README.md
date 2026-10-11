# RepoInsight AI

RepoInsight AI analyzes a GitHub repository without running its code. It clones
the repository, extracts facts with deterministic scanners and analyzers, sends
compact evidence to a local Ollama model for interpretation, then generates
architecture and project deliverables.

> **V1 status:** the implementation and offline test suite are in place. A live
> Ollama-backed end-to-end run still needs to be completed with a model installed.
> The UI screenshots are not checked into this repository yet; see
> [Screenshots](#screenshots).

## Features

- Clone and scan a GitHub repository, with configurable file and size limits.
- Detect languages, dependencies, configuration, important files, and supported
  frameworks.
- Detect API endpoints for FastAPI, Flask, Express, and Spring Boot.
- Analyze database, authentication, external-service, and rule-based security
  evidence.
- Build a compact, bounded LLM context; the full repository is never sent to
  Ollama.
- Generate architecture diagrams in PNG, SVG, and Mermaid formats.
- Generate a 13-section PDF report, a 10-slide PowerPoint, and structured JSON.
- Provide a FastAPI backend and a Streamlit interface with run progress, history,
  analysis tabs, and artifact downloads.
- Remove the cloned repository when its analysis finishes; repository code is
  only read and parsed, never executed.

## Architecture

```text
GitHub URL
    |
    v
Clone and bounded scan
    |
    v
Deterministic analyzers
  | repository | APIs | database | auth | external services | security |
    |
    v
Compact, evidence-based context ----> Local Ollama interpretation
    |                                          |
    +------------------+-----------------------+
                       v
             Validated analysis data
                       |
        +--------------+--------------+
        v              v              v
  Graphviz diagrams  PDF / PPTX   Structured JSON
        |
        v
 FastAPI and Streamlit
```

## Technology stack

| Area | Technologies |
| --- | --- |
| Language | Python 3.11+ |
| Frontend / backend | Streamlit / FastAPI |
| Local LLM | Ollama; model selected with `OLLAMA_MODEL` |
| Repository access | GitPython |
| Analysis and validation | Python AST, framework analyzers, Pydantic |
| Diagram / report / slides | Graphviz, ReportLab, python-pptx |
| Persistence | SQLite |
| Quality | pytest, Ruff |

The `tree-sitter` package is listed as a dependency, but tree-sitter parsing is
not currently wired into the analyzers.

## Installation

Install Python 3.11 or newer, Git, Graphviz, and Ollama first. Graphviz must
include its system `dot` executable on `PATH`; the Python package alone is not
enough. Verify the tools from PowerShell:

```powershell
python --version
git --version
dot -V
ollama list
```

From the repository root, create an environment and install the Python
dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks virtual-environment activation, use the Python executable
inside `.venv` directly, for example `.venv\Scripts\python.exe -m pip install
-r requirements.txt`.

Start Ollama, then pull the model configured below (the model download may be
large):

```powershell
ollama pull qwen3-coder
ollama list
```

If Ollama is not already running as a service, start it in a separate terminal
with `ollama serve`.

## Configuration

Edit the local `.env` file. It is ignored by Git. Ollama settings and scanner
limits are read when the service starts.

| Variable | Default | Description |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `qwen3-coder` | Installed Ollama model name |
| `OLLAMA_NUM_CTX` | `8192` | Model context budget |
| `GITHUB_TOKEN` | empty | Optional GitHub token for repository access |
| `MAX_REPO_MB` | `100` | Maximum aggregate repository data scanned |
| `MAX_FILES` | `5000` | Maximum number of scanned files |
| `MAX_FILE_KB` | `500` | Maximum size of an individual scanned file |
| `REPOINSIGHT_API_URL` | `http://localhost:8000` | Optional Streamlit backend URL override |

Use a token only when required, keep it private, and never commit `.env`. The
analyzers redact detected credential values from findings and do not include
`.env` values in generated reports.

## Run the application

Start the API backend and Streamlit UI in separate terminals from the project
root, with the virtual environment active:

```powershell
uvicorn app.main:app --reload
```

```powershell
streamlit run frontend/app.py
```

Open the Streamlit URL printed in the terminal (normally
`http://localhost:8501`). Check that the backend and Ollama are online in the
sidebar before starting an analysis. Ollama is needed for LLM-generated
architecture interpretation and slide content; if it is unavailable,
architecture analysis may use its deterministic fallback, but presentation
generation can fail.

## Usage

1. Open the Streamlit page and enter a repository URL in the form
   `https://github.com/<owner>/<repo>`.
2. Select **Analyze Repository** and watch the progress status.
3. Review the Overview, Architecture, APIs, Security, and Report tabs.
4. Download the PDF, PPTX, JSON, PNG, or SVG from Downloads.

The analysis is also available through the API. For example:

```http
POST http://localhost:8000/analyze
Content-Type: application/json

{"repository_url":"https://github.com/owner/repo"}
```

The request returns a run ID. Poll `GET /status/{id}` until its status is
`completed`, then retrieve `GET /results/{id}` or download an artifact. The
available routes are:

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/analyze` | Start an analysis |
| `GET` | `/status/{id}` | Read status and progress |
| `GET` | `/results/{id}` | Retrieve completed structured results |
| `GET` | `/download/{id}/{type}` | Download `pdf`, `pptx`, `json`, `png`, or `svg` |

The service stores run data in SQLite. It can reuse a completed analysis when
the repository URL and commit SHA match and the cached artifacts still exist.
The Streamlit history is scoped to the current browser session.

## Supported frameworks

V1 endpoint analysis covers:

| Framework | Endpoint patterns |
| --- | --- |
| FastAPI | Route decorators and router prefixes |
| Flask | Route decorators |
| Express | App/router methods and mounted-router prefixes |
| Spring Boot | Class and method mapping annotations |

Other detected technologies, such as React or Next.js, may appear in repository
analysis, but do not imply additional API endpoint analyzers.

## Generated outputs

- **PDF:** project overview, problem statement, objectives, technology stack,
  repository structure, architecture, endpoints, database, modules, workflow,
  security observations, dependencies, and future enhancements.
- **PPTX:** exactly 10 slides, including architecture and endpoint summaries.
- **JSON:** structured scan and analyzer results.
- **PNG / SVG:** Graphviz architecture diagrams.
- **Mermaid:** generated locally when available; it is not currently offered by
  the API or UI download controls.

Artifacts are written under `outputs/`. Temporary clones are stored under
`repositories/` and cleaned up after analysis. SQLite data is stored under
`database/`.

## Screenshots

No authentic application screenshots are checked in yet. The environment used
for this development did not have a browser capture tool or an installed Ollama
model for a successful end-to-end run, so mock screenshots are intentionally
not presented as verified output. After completing a live run, save captures
under `docs/screenshots/` and embed them here. Useful captures are the initial
URL form, completed Overview, Architecture and APIs tabs, and Downloads.

## Testing and code quality

Run the offline test suite and lint check from the repository root:

```powershell
python -m pytest -q
ruff check .
```

The latest full-suite run before this documentation update reported 51 passed
and 2 skipped. The skips were the live Ollama test (no server/model available)
and the symlink test (platform permissions). The repository-wide Ruff check
currently reports lint findings and is not yet clean.

## Limitations

- Analysis is static and heuristic; it may miss indirect routes, dynamically
  constructed configuration, or technologies not covered by the analyzers.
- Scanner file, per-file, and aggregate-size limits can exclude repository
  content from results.
- A local Ollama installation with the configured model is needed for a complete
  presentation-generation run. Live Ollama behavior has not yet been validated
  in this environment.
- Tree-sitter-based source parsing is not yet integrated.
- Security findings are rule-based observations, not a security audit or
  certification.
- Private repository access depends on GitHub token permissions and has not
  been verified as part of a live end-to-end run.

## Future scope

- Capture real screenshots after a verified end-to-end demo.
- Integrate tree-sitter parsing for supported non-Python source languages.
- Complete live Ollama validation, including structured output and generated
  artifacts.
- Continue reducing repository-wide Ruff findings and expanding realistic
  framework and failure-mode integration tests.

## 2–3 minute demonstration

Use a small public repository with recognizable routes, and make sure the API,
Streamlit, Graphviz, and configured Ollama model are available before recording.

| Time | Demonstration |
| --- | --- |
| `0:00–0:20` | Open RepoInsight AI; point out backend and Ollama connection status. |
| `0:20–0:40` | Paste the public GitHub URL and select **Analyze Repository**. |
| `0:40–1:00` | Show progress as the repository is scanned and analyzed. |
| `1:00–1:25` | Review detected languages, frameworks, dependencies, and file tree. |
| `1:25–1:50` | Show the architecture diagram and detected API endpoint table. |
| `1:50–2:10` | Review database, authentication, external services, and security findings. |
| `2:10–2:40` | Download the PDF, PPTX, and JSON; close by noting the clone is cleaned up. |
