import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from src.crewai_enterprise.server.task_config import get_task_config

router = APIRouter()


@router.get("/task/{task_id}", response_class=HTMLResponse)
def task_page(task_id: int):
    return HTMLResponse("<html><body><div id='app'>Loading...</div></body></html>")


@router.get("/api/task/{task_id}/files")
def list_task_files(task_id: int):
    cfg = get_task_config()
    files_dir = os.path.join(cfg.storage_root, f"task-{task_id}", "files")
    if not os.path.isdir(files_dir):
        return {"files": []}
    return {"files": sorted(os.listdir(files_dir))}


@router.get("/api/task/{task_id}/files/{filename}")
def download_task_file(task_id: int, filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    cfg = get_task_config()
    path = os.path.join(cfg.storage_root, f"task-{task_id}", "files", filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)
