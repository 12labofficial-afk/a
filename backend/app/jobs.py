import json
import os
import shutil
import threading
import traceback
import uuid
import zipfile

from app import config, llm
from app.schemas import ProjectJson, JobStatus
from app.audio_utils import extract_audio_chunks, DialogueAudio, build_combined_audio_track
from app.rig_assets import load_character_parts
from app.video_renderer import render_video

_jobs_lock = threading.Lock()
_jobs = {}


def _job_dir(job_id: str) -> str:
    return os.path.join(config.JOBS_DIR, job_id)


def create_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    os.makedirs(_job_dir(job_id), exist_ok=True)
    with _jobs_lock:
        _jobs[job_id] = JobStatus(job_id=job_id, state="queued", progress=0, message="Job queued")
    return job_id


def get_job(job_id: str) -> JobStatus:
    with _jobs_lock:
        return _jobs.get(job_id)


def _update(job_id: str, **kwargs):
    with _jobs_lock:
        job = _jobs[job_id]
        for k, v in kwargs.items():
            setattr(job, k, v)


def video_path(job_id: str) -> str:
    return os.path.join(_job_dir(job_id), "output.mp4")


def start_job(job_id: str, project_json_str: str, audio_zip_path: str, characters_zip_path: str, fps: int, width: int, height: int):
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, project_json_str, audio_zip_path, characters_zip_path, fps, width, height),
        daemon=True,
    )
    thread.start()


def _run_job(job_id, project_json_str, audio_zip_path, characters_zip_path, fps, width, height):
    jdir = _job_dir(job_id)
    try:
        _update(job_id, state="processing", progress=2, message="JSON parse ho raha hai...")
        project = ProjectJson.model_validate_json(project_json_str)

        _update(job_id, progress=5, message="Audio zip se dialogue chunks nikale ja rahe hain...")
        audio_dir = os.path.join(jdir, "audio_chunks")
        chunk_paths = extract_audio_chunks(audio_zip_path, audio_dir)
        if len(chunk_paths) != len(project.dialogues):
            n = min(len(chunk_paths), len(project.dialogues))
            chunk_paths = chunk_paths[:n]

        _update(job_id, progress=10, message="Har audio chunk ka amplitude envelope compute ho raha hai (lip-sync)...")
        dialogue_audios = []
        for i in range(len(project.dialogues)):
            if i < len(chunk_paths):
                dialogue_audios.append(DialogueAudio(chunk_paths[i]))
            else:
                dialogue_audios.append(None)

        _update(job_id, progress=15, message="Character rig assets load ho rahe hain...")
        chars_dir = os.path.join(jdir, "characters")
        os.makedirs(chars_dir, exist_ok=True)
        with zipfile.ZipFile(characters_zip_path) as zf:
            zf.extractall(chars_dir)

        character_parts = {}
        char_names = list(project.characterSettings.keys()) or sorted({d.character for d in project.dialogues})
        for name in char_names:
            folder = _find_character_folder(chars_dir, name)
            if folder:
                character_parts[name] = load_character_parts(folder)
            else:
                character_parts[name] = {}

        _update(job_id, progress=20, message="AI se har dialogue ke liye animation choreography maangi ja rahi hai...")
        choreographies = []
        for i, dlg in enumerate(project.dialogues):
            choreo = llm.get_choreography(dlg.character, dlg.line, dlg.emotion, project.genre)
            choreographies.append(choreo)
            _update(job_id, progress=20 + int((i + 1) / max(1, len(project.dialogues)) * 8),
                    message=f"Choreography {i + 1}/{len(project.dialogues)}: {dlg.character} -> {choreo['mode']}")

        _update(job_id, progress=28, message="Poora audio track timeline ke hisaab se mix ho raha hai...")
        total_duration = max((t.startTime + t.duration for t in project.timeline), default=1.0) + 1.0
        combined_audio_path = os.path.join(jdir, "combined_audio.wav")
        start_times = [t.startTime for t in project.timeline[: len(chunk_paths)]]
        build_combined_audio_track(chunk_paths, start_times, total_duration, combined_audio_path)

        def progress_cb(pct, msg):
            _update(job_id, progress=pct, message=msg)

        _update(job_id, progress=30, message="Video render shuru ho raha hai...")
        out_path = video_path(job_id)
        render_video(
            project, dialogue_audios, choreographies, character_parts,
            out_path, combined_audio_path, width, height, fps, progress_cb,
        )

        _update(job_id, state="done", progress=100, message="Video taiyaar hai!", video_ready=True)
    except Exception as e:
        traceback.print_exc()
        _update(job_id, state="error", message="Error aaya", error=str(e))


def _find_character_folder(chars_dir: str, character_name: str):
    for entry in os.listdir(chars_dir):
        full = os.path.join(chars_dir, entry)
        if os.path.isdir(full) and entry.strip().lower() == character_name.strip().lower():
            return full
    if os.listdir(chars_dir):
        only_dirs = [e for e in os.listdir(chars_dir) if os.path.isdir(os.path.join(chars_dir, e))]
        if len(only_dirs) == 1:
            return os.path.join(chars_dir, only_dirs[0])
    return None
