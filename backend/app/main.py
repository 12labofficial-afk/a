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
    characters_zip: UploadFile = File(...),
    bundle_zip: UploadFile = File(None),
    project_json: UploadFile = File(None),
    audio_zip: UploadFile = File(None),
    fps: int = Form(config.VIDEO_FPS),
    width: int = Form(config.VIDEO_WIDTH),
    height: int = Form(config.VIDEO_HEIGHT),
):
    """
    Two ways to supply the script + audio:
      - `bundle_zip`: the tool's own export — one zip holding json.json plus the numbered
        audio files together. This is the normal case.
      - `project_json` + `audio_zip`: the same two things uploaded separately.
    """
    job_id = jobs.create_job()
    jdir = jobs._job_dir(job_id)

    characters_zip_path = os.path.join(jdir, "characters.zip")
    with open(characters_zip_path, "wb") as f:
        f.write(await characters_zip.read())

    bundle_zip_path = None
    project_json_str = None
    audio_zip_path = None

    if bundle_zip is not None and bundle_zip.filename:
        bundle_zip_path = os.path.join(jdir, "bundle.zip")
        with open(bundle_zip_path, "wb") as f:
            f.write(await bundle_zip.read())
    elif project_json is not None and audio_zip is not None:
        project_json_str = (await project_json.read()).decode("utf-8")
        audio_zip_path = os.path.join(jdir, "audio.zip")
        with open(audio_zip_path, "wb") as f:
            f.write(await audio_zip.read())
    else:
        raise HTTPException(
            status_code=400,
            detail="Ya toh bundle_zip do (json.json + audio ek saath), ya project_json aur audio_zip dono alag-alag.",
        )

    if project_json_str is not None:
        try:
            from app.schemas import ProjectJson
            ProjectJson.model_validate_json(project_json_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid project JSON: {e}")

    jobs.start_job(
        job_id, characters_zip_path, fps, width, height,
        bundle_zip_path=bundle_zip_path, project_json_str=project_json_str, audio_zip_path=audio_zip_path,
    )
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
