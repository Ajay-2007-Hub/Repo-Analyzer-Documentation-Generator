import os
import time
from collections.abc import Callable
from typing import Any

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

DEFAULT_API_URL = os.getenv("REPOINSIGHT_API_URL", "http://localhost:8000").rstrip("/")
DEFAULT_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
POLL_INTERVAL_SECONDS = 1.5
MAX_ANALYSIS_WAIT_SECONDS = 30 * 60
OUTPUT_TYPES = ("pdf", "pptx", "json", "png", "svg")


class APIError(RuntimeError):
    """Friendly, user-displayable API error."""


def normalize_api_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ValueError("Backend URL must start with http:// or https://.")
    return url


def _response_error(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail")
        if isinstance(detail, dict):
            return str(detail.get("message", detail))
        if detail:
            return str(detail)
    except (ValueError, AttributeError):
        pass
    return f"Backend returned HTTP {response.status_code}."


def start_analysis(
    api_url: str,
    repository_url: str,
    *,
    session: Any = requests,
) -> dict[str, Any]:
    try:
        response = session.post(
            f"{normalize_api_url(api_url)}/analyze",
            json={"repository_url": repository_url.strip()},
            timeout=(5, 30),
        )
    except requests.RequestException as error:
        raise APIError(f"Could not reach the RepoInsight backend: {error}") from error
    if response.status_code not in (200, 202):
        raise APIError(_response_error(response))
    try:
        result = response.json()
    except ValueError as error:
        raise APIError("Backend returned an invalid response for the analysis request.") from error
    if not result.get("id"):
        raise APIError("Backend did not return an analysis run ID.")
    return result


def poll_analysis(
    api_url: str,
    run_id: str,
    on_progress: Callable[[str, str], None] | None = None,
    *,
    session: Any = requests,
    timeout_seconds: int = MAX_ANALYSIS_WAIT_SECONDS,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    endpoint = f"{normalize_api_url(api_url)}/status/{run_id}"
    deadline = time.monotonic() + timeout_seconds
    last_progress = ""
    while time.monotonic() < deadline:
        try:
            response = session.get(endpoint, timeout=(5, 30))
        except requests.RequestException as error:
            raise APIError(f"Could not retrieve analysis progress: {error}") from error
        if response.status_code != 200:
            raise APIError(_response_error(response))
        try:
            status = response.json()
        except ValueError as error:
            raise APIError("Backend returned invalid analysis status data.") from error

        current_status = status.get("status")
        progress = str(status.get("progress") or current_status or "Processing")
        if progress != last_progress and on_progress:
            on_progress(current_status or "running", progress)
        last_progress = progress

        if current_status == "completed":
            return status
        if current_status == "failed":
            detail = status.get("error") or "Analysis failed without an error message."
            raise APIError(str(detail))
        if current_status not in {"queued", "running"}:
            raise APIError(f"Backend returned unknown analysis status: {current_status!r}")
        sleep(poll_interval)

    raise APIError(
        f"Analysis is still running after {timeout_seconds // 60} minutes. "
        f"Run ID: {run_id}"
    )


def fetch_results(
    api_url: str,
    run_id: str,
    *,
    session: Any = requests,
) -> dict[str, Any]:
    try:
        response = session.get(
            f"{normalize_api_url(api_url)}/results/{run_id}",
            timeout=(5, 60),
        )
    except requests.RequestException as error:
        raise APIError(f"Could not retrieve analysis results: {error}") from error
    if response.status_code != 200:
        raise APIError(_response_error(response))
    try:
        result = response.json()
    except ValueError as error:
        raise APIError("Backend returned invalid analysis results.") from error
    if not isinstance(result.get("analysis"), dict):
        raise APIError("Backend results did not include analysis data.")
    return result


def fetch_download(
    api_url: str,
    run_id: str,
    output_type: str,
    *,
    session: Any = requests,
) -> bytes:
    if output_type not in OUTPUT_TYPES:
        raise ValueError(f"Unsupported download type: {output_type}")
    try:
        response = session.get(
            f"{normalize_api_url(api_url)}/download/{run_id}/{output_type}",
            timeout=(5, 120),
        )
    except requests.RequestException as error:
        raise APIError(f"Could not download {output_type.upper()}: {error}") from error
    if response.status_code != 200:
        raise APIError(_response_error(response))
    return response.content


def check_ollama(ollama_host: str, *, session: Any = requests) -> tuple[bool, str]:
    try:
        response = session.get(
            f"{ollama_host.rstrip('/')}/api/tags", timeout=(3, 5)
        )
        if response.status_code == 200:
            return True, "Ollama is available."
        return False, f"Ollama returned HTTP {response.status_code}."
    except requests.RequestException as error:
        return False, str(error)


def check_backend(api_url: str, *, session: Any = requests) -> tuple[bool, str]:
    try:
        response = session.get(
            f"{normalize_api_url(api_url)}/openapi.json", timeout=(3, 5)
        )
        if response.status_code == 200:
            return True, "RepoInsight backend is available."
        return False, f"Backend returned HTTP {response.status_code}."
    except (requests.RequestException, ValueError) as error:
        return False, str(error)


def _format_table_rows(items: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    return [{key: item.get(key, "") for key in keys} for item in items]


def _render_download(
    api_url: str, run_id: str, output_type: str, label: str
) -> None:
    try:
        payload = fetch_download(api_url, run_id, output_type)
    except APIError as error:
        st.error(str(error))
        return
    media_types = {
        "pdf": "application/pdf",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "json": "application/json",
        "png": "image/png",
        "svg": "image/svg+xml",
    }
    st.download_button(
        label=label,
        data=payload,
        file_name=f"repoinsight-{run_id[:8]}.{output_type}",
        mime=media_types[output_type],
        key=f"download-{run_id}-{output_type}",
    )


def _render_analysis(api_url: str, result: dict[str, Any]) -> None:
    analysis = result["analysis"]
    run = result.get("run", {})
    run_id = run.get("id", "")
    scan = analysis.get("scan", {})
    project = analysis.get("project", {}).get("repo_info", {})
    endpoints = analysis.get("endpoints", [])
    architecture = analysis.get("architecture") or {}
    security = analysis.get("security_findings", [])
    database = analysis.get("database") or {}
    authentication = analysis.get("authentication") or {}
    external_services = analysis.get("external_services", [])

    overview_tab, architecture_tab, apis_tab, security_tab, report_tab, downloads_tab = (
        st.tabs(
            [
                "Overview",
                "Architecture",
                "APIs",
                "Security",
                "Report",
                "Downloads",
            ]
        )
    )

    with overview_tab:
        st.subheader(scan.get("repository_name", "Repository"))
        col_files, col_lines, col_size = st.columns(3)
        col_files.metric("Files scanned", f"{scan.get('total_files', 0):,}")
        col_lines.metric("Lines", f"{scan.get('total_lines', 0):,}")
        col_size.metric("Repository size", f"{scan.get('total_size_mb', 0):.2f} MB")
        st.caption(f"Commit: `{scan.get('commit_sha', 'Not detected')}`")
        st.markdown("**Languages**")
        languages = project.get("languages") or {}
        if languages:
            st.dataframe(
                [
                    {"Language": language, "Share": f"{percentage:.1f}%"}
                    for language, percentage in languages.items()
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No programming languages detected.")
        st.markdown("**Frameworks**")
        frameworks = project.get("frameworks") or []
        st.write(", ".join(frameworks) if frameworks else "Not detected")
        st.markdown("**Dependencies**")
        dependencies = project.get("dependencies") or []
        if dependencies:
            st.write(", ".join(dependencies))
        else:
            st.write("Not detected")
        st.markdown("**Repository file tree**")
        st.json(scan.get("file_tree") or {}, expanded=False)

    with architecture_tab:
        st.subheader(architecture.get("title", "Architecture"))
        if architecture.get("description"):
            st.write(architecture["description"])
        try:
            png = fetch_download(api_url, run_id, "png")
            st.image(png, caption="Detected architecture", use_container_width=True)
        except APIError as error:
            st.warning(f"Architecture preview unavailable: {error}")
        nodes = architecture.get("nodes") or []
        edges = architecture.get("edges") or []
        if nodes:
            st.markdown("**Components**")
            st.dataframe(
                _format_table_rows(nodes, ["label", "node_type", "description"]),
                hide_index=True,
                use_container_width=True,
            )
        if edges:
            st.markdown("**Connections**")
            st.dataframe(
                _format_table_rows(edges, ["from_node", "to_node", "label", "edge_type"]),
                hide_index=True,
                use_container_width=True,
            )
        if not nodes:
            st.info("No architecture components were detected.")

    with apis_tab:
        st.subheader("Detected API endpoints")
        if endpoints:
            st.dataframe(
                _format_table_rows(
                    endpoints, ["method", "path", "file", "description"]
                ),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No API endpoints detected.")

    with security_tab:
        st.subheader("Security observations")
        col_db, col_auth = st.columns(2)
        col_db.metric("Database", database.get("db_type", "Not detected"))
        col_auth.metric(
            "Authentication", authentication.get("mechanism", "Not detected")
        )
        if database.get("orm"):
            st.caption(f"ORM: {database['orm']}")
        if database.get("models"):
            st.caption(f"Models: {', '.join(database['models'])}")
        if external_services:
            st.markdown("**External service domains**")
            st.write(", ".join(item.get("domain", "") for item in external_services))
        else:
            st.write("External services: Not detected")
        if security:
            st.dataframe(
                _format_table_rows(
                    security,
                    ["severity", "category", "file", "line", "description"],
                ),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.success("No rule-based security findings detected.")
            st.caption("This is not a security certification.")

    with report_tab:
        st.subheader("Generated project report")
        st.write(
            "The PDF contains 13 report sections covering the repository and detected evidence."
        )
        _render_download(api_url, run_id, "pdf", "Download PDF report")
        st.markdown("**Important source files**")
        top_files = analysis.get("project", {}).get("top_files", [])
        if top_files:
            st.dataframe(
                _format_table_rows(top_files, ["path", "score", "reason"]),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.write("Not detected")

    with downloads_tab:
        st.subheader("Download generated outputs")
        download_columns = st.columns(len(OUTPUT_TYPES))
        labels = {
            "pdf": "PDF",
            "pptx": "PPTX",
            "json": "JSON",
            "png": "PNG",
            "svg": "SVG",
        }
        for column, output_type in zip(download_columns, OUTPUT_TYPES):
            with column:
                _render_download(
                    api_url, run_id, output_type, f"Download {labels[output_type]}"
                )


def main() -> None:
    st.set_page_config(
        page_title="RepoInsight AI",
        page_icon="🔎",
        layout="wide",
    )
    st.title("RepoInsight AI")
    st.caption("Turn a public GitHub repository into an architecture and project analysis.")
    if "history" not in st.session_state:
        st.session_state.history = []
    if "selected_result" not in st.session_state:
        st.session_state.selected_result = None

    with st.sidebar:
        st.subheader("Connection settings")
        api_url = st.text_input("FastAPI backend URL", value=DEFAULT_API_URL)
        ollama_host = st.text_input("Ollama host", value=DEFAULT_OLLAMA_HOST)
        is_backend_available, backend_detail = check_backend(api_url)
        if is_backend_available:
            st.success("Backend is online.")
        else:
            st.warning(
                "RepoInsight backend is offline or unreachable. Start FastAPI before analysis."
            )
            st.caption(backend_detail)
        is_ollama_available, ollama_detail = check_ollama(ollama_host)
        if is_ollama_available:
            st.success("Ollama is online.")
        else:
            st.warning(
                "Ollama is offline or unreachable. Architecture and presentation "
                "generation may fail or use the architecture fallback."
            )
            st.caption(ollama_detail)

    repository_url = st.text_input(
        "GitHub Repository URL",
        placeholder="https://github.com/owner/repository",
        key="repository_url",
    )

    if st.button(
        "Analyze Repository",
        type="primary",
        disabled=not repository_url.strip(),
        use_container_width=False,
    ):
        try:
            normalized_api_url = normalize_api_url(api_url)
            started = start_analysis(normalized_api_url, repository_url)
            run_id = started["id"]
            progress_container = st.status(
                "Starting repository analysis...",
                expanded=True,
                state="running",
            )
            progress_line = progress_container.empty()

            def update_progress(status: str, message: str) -> None:
                progress_line.write(f"⏳ {message}")
                progress_container.update(
                    label=message,
                    state="running",
                    expanded=True,
                )

            poll_analysis(
                normalized_api_url,
                run_id,
                on_progress=update_progress,
            )
            progress_container.update(
                label="Analysis complete",
                state="complete",
                expanded=False,
            )
            result = fetch_results(normalized_api_url, run_id)
            st.session_state.selected_result = result
            if not any(item["id"] == run_id for item in st.session_state.history):
                st.session_state.history.insert(
                    0,
                    {
                        "id": run_id,
                        "repository_url": repository_url.strip(),
                    },
                )
            st.rerun()
        except (ValueError, APIError) as error:
            st.error(str(error))
        except requests.RequestException as error:
            st.error(f"Could not connect to the analysis service: {error}")

    if st.session_state.history:
        with st.expander("Analysis history", expanded=False):
            options = st.session_state.history
            selected_id = st.selectbox(
                "Recent runs",
                options=[item["id"] for item in options],
                format_func=lambda run_id: next(
                    (
                        f"{item['repository_url']} ({run_id[:8]})"
                        for item in options
                        if item["id"] == run_id
                    ),
                    run_id,
                ),
            )
            if st.button("Load selected analysis"):
                try:
                    st.session_state.selected_result = fetch_results(
                        normalize_api_url(api_url), selected_id
                    )
                    st.rerun()
                except APIError as error:
                    st.error(str(error))

    selected_result = st.session_state.selected_result
    if selected_result:
        _render_analysis(normalize_api_url(api_url), selected_result)
    else:
        st.info("Paste a public GitHub repository URL, then select **Analyze Repository**.")


if __name__ == "__main__":
    main()
