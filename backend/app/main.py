import io
import json
import os
import shutil
import uuid

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


@app.post("/api/fla/upload")
async def fla_upload(fla: UploadFile = File(...)):
    """Upload a .fla (XFL) file. It's stored on our own server disk (no
    third-party storage) and scanned for symbols that have REAL, artist-built
    multi-keyframe motion -- a walk cycle, a blink, a bow-draw -- as opposed
    to a single static pose."""
    from app import fla_inspector

    fla_id = uuid.uuid4().hex[:12]
    fla_dir = os.path.join(config.DATA_DIR, "fla", fla_id)
    os.makedirs(fla_dir, exist_ok=True)

    raw_path = os.path.join(fla_dir, "original.fla")
    with open(raw_path, "wb") as f:
        f.write(await fla.read())

    extract_dir = os.path.join(fla_dir, "extract")
    try:
        fla_inspector.repair_and_extract(raw_path, extract_dir)
        animations = fla_inspector.list_animated_symbols(extract_dir)
    except Exception as e:
        shutil.rmtree(fla_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"FLA process nahi ho payi: {e}")

    with open(os.path.join(fla_dir, "animations.json"), "w") as f:
        json.dump(animations, f)

    return {"fla_id": fla_id, "filename": fla.filename, "animations": animations}


@app.get("/api/fla/{fla_id}/animations")
def fla_animations(fla_id: str):
    anim_json = os.path.join(config.DATA_DIR, "fla", fla_id, "animations.json")
    if not os.path.exists(anim_json):
        raise HTTPException(status_code=404, detail="Ye FLA nahi mili -- dubara upload karo.")
    with open(anim_json) as f:
        return {"fla_id": fla_id, "animations": json.load(f)}


@app.get("/api/fla/{fla_id}/preview")
def fla_preview(fla_id: str, symbol: str, seconds: float = 0.0):
    """Render (and cache) a clip for one detected animation at the file's own
    frame rate. `seconds` loops it up to at least that long."""
    from app import fla_inspector

    fla_dir = os.path.join(config.DATA_DIR, "fla", fla_id)
    extract_dir = os.path.join(fla_dir, "extract")
    if not os.path.isdir(extract_dir):
        raise HTTPException(status_code=404, detail="Ye FLA nahi mili -- dubara upload karo.")

    seconds = max(0.0, min(seconds, 60.0))
    preview_dir = os.path.join(fla_dir, "previews")
    suffix = f"_{seconds:g}s" if seconds else ""
    out_path = os.path.join(preview_dir, fla_inspector.safe_name(symbol) + suffix + ".mp4")
    if not os.path.exists(out_path):
        try:
            fla_inspector.render_preview(extract_dir, symbol, out_path, min_seconds=seconds)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Ye animation preview nahi ban payi: {e}")

    return FileResponse(out_path, media_type="video/mp4")


@app.post("/api/fla/{fla_id}/lipsync")
async def fla_lipsync(fla_id: str, symbol: str = Form(...), audio: UploadFile = File(...)):
    """Real audio-driven lip-sync: finds a real mouth/lip-shape symbol inside
    `symbol` and swaps it frame-by-frame to match the uploaded audio's
    amplitude -- no invented motion, every mouth pose is a real keyframe."""
    from app import fla_inspector

    fla_dir = os.path.join(config.DATA_DIR, "fla", fla_id)
    extract_dir = os.path.join(fla_dir, "extract")
    if not os.path.isdir(extract_dir):
        raise HTTPException(status_code=404, detail="Ye FLA nahi mili -- dubara upload karo.")

    audio_dir = os.path.join(fla_dir, "lipsync_audio")
    os.makedirs(audio_dir, exist_ok=True)
    audio_path = os.path.join(audio_dir, f"{uuid.uuid4().hex[:12]}_{audio.filename}")
    with open(audio_path, "wb") as f:
        f.write(await audio.read())

    out_dir = os.path.join(fla_dir, "lipsync")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{fla_inspector.safe_name(symbol)}_{uuid.uuid4().hex[:8]}.mp4")
    try:
        info = fla_inspector.render_lipsync(extract_dir, symbol, audio_path, out_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Lipsync nahi ban paya: {e}")

    return FileResponse(out_path, media_type="video/mp4",
                         headers={"X-Mouth-Symbol": info["mouth_symbol"], "X-Target-Layer": info["target_layer"]})


@app.post("/api/fla/{fla_id}/attach-prop")
async def fla_attach_prop(
    fla_id: str,
    symbol: str = Form(...),
    prop_fla_id: str = Form(...),
    prop_symbol: str = Form(...),
    parent_layer: str = Form(...),
    offset_x: float = Form(0.0),
    offset_y: float = Form(0.0),
    seconds: float = Form(0.0),
):
    """Rigidly attach a static prop (from a possibly different uploaded FLA --
    e.g. a weapon/tool drawn on its own) to one real layer of `symbol`. The
    prop follows that layer's own real, already-authored matrix every frame
    plus a fixed local offset -- no new motion is invented, the prop just
    rides along with whatever real motion that layer already has."""
    from app import fla_inspector

    fla_dir = os.path.join(config.DATA_DIR, "fla", fla_id)
    extract_dir = os.path.join(fla_dir, "extract")
    if not os.path.isdir(extract_dir):
        raise HTTPException(status_code=404, detail="Ye FLA nahi mili -- dubara upload karo.")

    prop_extract_dir = os.path.join(config.DATA_DIR, "fla", prop_fla_id, "extract")
    if not os.path.isdir(prop_extract_dir):
        raise HTTPException(status_code=404, detail="Prop wali FLA nahi mili -- dubara upload karo.")

    out_symbol = f"{fla_inspector.safe_name(symbol)}_{fla_inspector.safe_name(prop_symbol)}_{uuid.uuid4().hex[:6]}"
    try:
        out_symbol = fla_inspector.attach_prop(
            extract_dir, symbol, prop_extract_dir, prop_symbol,
            parent_layer, (offset_x, offset_y), out_symbol,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Prop attach nahi ho paya: {e}")

    out_dir = os.path.join(fla_dir, "previews")
    os.makedirs(out_dir, exist_ok=True)
    seconds = max(0.0, min(seconds, 60.0))
    suffix = f"_{seconds:g}s" if seconds else ""
    out_path = os.path.join(out_dir, out_symbol + suffix + ".mp4")
    if not os.path.exists(out_path):
        try:
            fla_inspector.render_preview(extract_dir, out_symbol, out_path, min_seconds=seconds)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Preview nahi ban payi: {e}")

    return FileResponse(out_path, media_type="video/mp4", headers={"X-Composite-Symbol": out_symbol})


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
