from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.agents.manager import AnalysisManager
from app.models.api import AnalyzeRequest, AnalyzeResponse

app = FastAPI(
    title="RepoInsight AI",
    version="1.0.0",
    description="Analyze public GitHub repositories and generate reports.",
)
manager = AnalysisManager()


@app.post("/analyze", response_model=AnalyzeResponse, status_code=202)
def analyze_repository(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        run_id = manager.start(request.repository_url)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return AnalyzeResponse(
        id=run_id,
        status="queued",
        progress="Queued for analysis",
    )


@app.get("/status/{run_id}")
def get_status(run_id: str) -> dict:
    result = manager.get_status(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    return result


@app.get("/results/{run_id}")
def get_results(run_id: str) -> dict:
    result = manager.get_results(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    if result["run"]["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Analysis results are not ready.",
                "status": result["run"]["status"],
                "progress": result["run"]["progress"],
            },
        )
    return result


@app.get("/download/{run_id}/{output_type}")
def download_output(run_id: str, output_type: str) -> FileResponse:
    try:
        path = manager.get_download(run_id, output_type)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="Analysis run or requested output not found.",
        )
    media_types = {
        "pdf": "application/pdf",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "json": "application/json",
        "png": "image/png",
        "svg": "image/svg+xml",
    }
    return FileResponse(
        path,
        media_type=media_types[output_type],
        filename=path.name,
    )
