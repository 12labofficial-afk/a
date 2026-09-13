import io
import os
import shutil

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

from app import config, jobs

app = FastAPI(title="AI Script-to-Animation Studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/jobs")
async def create_job(
    project_json: UploadFile = File(...),
    audio_zip: UploadFile = File(...),
    characters_zip: UploadFile = File(...),
    fps: int = Form(config.VIDEO_FPS),
    width: int = Form(config.VIDEO_WIDTH),
    height: int = Form(config.VIDEO_HEIGHT),
):
    job_id = jobs.create_job()
    jdir = jobs._job_dir(job_id)

    project_bytes = await project_json.read()
    project_json_str = project_bytes.decode("utf-8")

    audio_zip_path = os.path.join(jdir, "audio.zip")
    with open(audio_zip_path, "wb") as f:
        f.write(await audio_zip.read())

    characters_zip_path = os.path.join(jdir, "characters.zip")
    with open(characters_zip_path, "wb") as f:
        f.write(await characters_zip.read())

    try:
        from app.schemas import ProjectJson
        ProjectJson.model_validate_json(project_json_str)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid project JSON: {e}")

    jobs.start_job(job_id, project_json_str, audio_zip_path, characters_zip_path, fps, width, height)
    return {"job_id": job_id}


@app.post("/api/preview-character")
async def preview_character(sheet: UploadFile = File(...)):
    """Upload one character sheet PNG, get back a rendered preview + detected part count."""
    from app.rig_autoslice import auto_slice_sheet
    from app.video_renderer import render_character_preview

    try:
        raw = await sheet.read()
        img = Image.open(io.BytesIO(raw))
        parts = auto_slice_sheet(img)
        if len(parts) < 3:
            raise HTTPException(
                status_code=422,
                detail="Sheet me pehchane jaane layak parts nahi mile. Sheet transparent PNG honi chahiye "
                       "aur usi fixed layout me (body/head/mouths/arms/legs scattered) honi chahiye.",
            )
        preview = render_character_preview(parts)
        buf = io.BytesIO()
        preview.save(buf, format="PNG")
        detected = ",".join(sorted(parts.keys()))
        return Response(
            content=buf.getvalue(),
            media_type="image/png",
            headers={"X-Detected-Parts": detected, "X-Part-Count": str(len(parts))},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Sheet process nahi ho payi: {e}")


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs/{job_id}/video")
def job_video(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    path = jobs.video_path(job_id)
    if not job.video_ready or not os.path.exists(path):
        raise HTTPException(status_code=409, detail="Video abhi taiyaar nahi hai")
    return FileResponse(path, media_type="video/mp4", filename=f"{job_id}.mp4")


frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
