"""
FastAPI application for epubkit — EPUB optimizer for e-ink readers.
Handles: file upload, metadata preview, SSE progress streaming, file download.
"""

import os
import json
import uuid
import shutil
import asyncio
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from epub_processor import process_epub, extract_epub_metadata, ProcessingOptions, ProcessingReport

app = FastAPI(title="epubkit")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Temp directory for uploads and outputs
TEMP_DIR = Path("./tmp")
UPLOAD_DIR = TEMP_DIR / "uploads"
OUTPUT_DIR = TEMP_DIR / "outputs"
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

# Thread pool for processing
executor = ThreadPoolExecutor(max_workers=4)

# In-memory task tracking
tasks: dict = {}


@app.on_event("startup")
async def startup():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Start cleanup background task
    asyncio.create_task(cleanup_old_files())


async def cleanup_old_files():
    """Remove temp files older than 1 hour."""
    while True:
        await asyncio.sleep(300)  # Check every 5 minutes
        cutoff = time.time() - 3600
        for d in [UPLOAD_DIR, OUTPUT_DIR]:
            if d.exists():
                for item in d.iterdir():
                    if item.is_dir() and item.stat().st_mtime < cutoff:
                        shutil.rmtree(item, ignore_errors=True)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """Upload one or more EPUB files. Returns task IDs and metadata for each."""
    results = []

    for file in files:
        if not file.filename or not file.filename.lower().endswith('.epub'):
            results.append({
                "filename": file.filename,
                "error": "Not an EPUB file",
                "task_id": None,
            })
            continue

        # Check for .kepub.epub
        if file.filename.lower().endswith('.kepub.epub'):
            results.append({
                "filename": file.filename,
                "error": "Kobo EPUB files (.kepub.epub) are not supported",
                "task_id": None,
            })
            continue

        task_id = str(uuid.uuid4())
        task_dir = UPLOAD_DIR / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        # Save uploaded file
        file_path = task_dir / file.filename
        content = await file.read()

        if len(content) > MAX_FILE_SIZE:
            results.append({
                "filename": file.filename,
                "error": f"File too large (max {MAX_FILE_SIZE // (1024*1024)}MB)",
                "task_id": None,
            })
            continue

        with open(file_path, 'wb') as f:
            f.write(content)

        # Extract metadata for preview
        try:
            metadata = extract_epub_metadata(str(file_path))
        except Exception as e:
            metadata = {"title": "", "author": "", "error": str(e)}

        tasks[task_id] = {
            "status": "uploaded",
            "filename": file.filename,
            "file_path": str(file_path),
            "file_size": len(content),
        }

        results.append({
            "filename": file.filename,
            "task_id": task_id,
            "file_size": len(content),
            "metadata": metadata,
            "error": metadata.get("error"),
        })

    return {"files": results}


@app.get("/process/{task_id}")
async def process_sse(
    task_id: str,
    grayscale: bool = True,
    contrast: bool = True,
    quality: int = 70,
    remove_fonts: bool = True,
    remove_css: bool = True,
    light_novel: bool = False,
    generate_cover: bool = True,
    clean_metadata: bool = True,
    text_cleanup: bool = True,
    edit_title: str = "",
    edit_author: str = "",
):
    """SSE endpoint that streams processing progress."""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    if task["status"] == "processing":
        raise HTTPException(status_code=409, detail="Already processing")

    input_path = task["file_path"]
    out_dir = OUTPUT_DIR / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(out_dir / "output.epub")

    options = ProcessingOptions(
        grayscale=grayscale,
        contrast_boost=contrast,
        quality=quality,
        remove_fonts=remove_fonts,
        remove_unused_css=remove_css,
        light_novel_mode=light_novel,
        generate_missing_cover=generate_cover,
        clean_metadata=clean_metadata,
        text_cleanup=text_cleanup,
    )

    if edit_title or edit_author:
        options.metadata_edits = {}
        if edit_title:
            options.metadata_edits['title'] = edit_title
        if edit_author:
            options.metadata_edits['author'] = edit_author

    task["status"] = "processing"

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def progress_callback(percent: int, message: str):
        loop.call_soon_threadsafe(queue.put_nowait, {
            "percent": percent,
            "message": message,
        })

    async def generate():
        # Start processing in thread pool
        future = loop.run_in_executor(
            executor,
            process_epub,
            input_path,
            output_path,
            options,
            progress_callback,
        )

        done = False
        while not done:
            try:
                update = await asyncio.wait_for(queue.get(), timeout=0.5)
                yield f"data: {json.dumps(update)}\n\n"
                if update.get("percent", 0) >= 100:
                    done = True
            except asyncio.TimeoutError:
                yield f": keepalive\n\n"

        # Wait for the processing to complete and get the report
        report: ProcessingReport = await future

        # Send final report
        final = {
            "percent": 100,
            "message": "Complete" if report.success else f"Error: {report.error}",
            "status": "done" if report.success else "error",
            "report": {
                "success": report.success,
                "error": report.error,
                "original_size": report.original_size,
                "optimized_size": report.optimized_size,
                "output_filename": report.output_filename,
                "summary": report.summary(),
                "images_converted": report.images_converted,
                "images_total": report.images_total,
                "fonts_removed": report.fonts_removed,
                "css_rules_removed": report.css_rules_removed,
                "svg_covers_fixed": report.svg_covers_fixed,
                "toc_status": report.toc_status,
                "metadata_items_stripped": report.metadata_items_stripped,
                "cover_generated": report.cover_generated,
                "attrs_stripped": report.attrs_stripped,
                "text_fixes_total": report.text_fixes_total,
                "text_cleanup_summary": report.text_cleanup_summary,
            }
        }

        task["status"] = "done" if report.success else "error"
        task["report"] = final["report"]
        task["output_path"] = output_path
        task["output_filename"] = report.output_filename

        yield f"data: {json.dumps(final)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/download/{task_id}")
async def download_file(task_id: str):
    """Download the processed EPUB file."""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    if task["status"] != "done":
        raise HTTPException(status_code=400, detail="Processing not complete")

    output_path = task.get("output_path")
    if not output_path or not os.path.exists(output_path):
        raise HTTPException(status_code=404, detail="Output file not found")

    filename = task.get("output_filename", "optimized.epub")

    return FileResponse(
        output_path,
        media_type="application/epub+zip",
        filename=filename,
    )


@app.get("/download-all")
async def download_all(task_ids: str):
    """Download multiple processed EPUBs as a ZIP. task_ids is comma-separated."""
    import zipfile
    ids = [t.strip() for t in task_ids.split(',') if t.strip()]

    if not ids:
        raise HTTPException(status_code=400, detail="No task IDs provided")

    # Create ZIP file
    zip_dir = OUTPUT_DIR / "batch"
    zip_dir.mkdir(parents=True, exist_ok=True)
    zip_path = str(zip_dir / f"x4_optimized_{uuid.uuid4().hex[:8]}.zip")

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for task_id in ids:
            if task_id in tasks and tasks[task_id]["status"] == "done":
                task = tasks[task_id]
                output_path = task.get("output_path", "")
                filename = task.get("output_filename", "optimized.epub")
                if os.path.exists(output_path):
                    zf.write(output_path, filename)

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename="x4_optimized_epubs.zip",
    )


if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get('PORT', 8000))
    uvicorn.run(app, host='0.0.0.0', port=port)
