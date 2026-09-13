import os
import re
import zipfile
import numpy as np
from pydub import AudioSegment

VALID_EXTS = (".wav", ".mp3", ".ogg", ".m4a", ".aac", ".flac")


def _natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def extract_bundle(bundle_zip_path: str, out_dir: str):
    """
    The tool's own export format: one zip holding both `json.json` (the project) and the
    numbered/named audio files ("001-अमित.wav", ...) side by side. Returns
    (project_json_str, chunk_paths) — chunk_paths naturally sorted, matching dialogue order.
    """
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(bundle_zip_path) as zf:
        json_name = next((n for n in zf.namelist() if os.path.basename(n).lower() == "json.json"), None)
        if json_name is None:
            raise ValueError("Bundle zip me json.json nahi mila.")
        project_json_str = zf.read(json_name).decode("utf-8")

    chunk_paths = extract_audio_chunks(bundle_zip_path, out_dir)
    return project_json_str, chunk_paths


def extract_audio_chunks(zip_path: str, out_dir: str) -> list:
    """Extracts audio files from the zip, naturally sorted (matching dialogue/timeline order)."""
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        names = [
            n for n in zf.namelist()
            if not n.endswith("/") and not os.path.basename(n).startswith((".", "__MACOSX"))
            and n.lower().endswith(VALID_EXTS)
        ]
        names.sort(key=_natural_key)
        paths = []
        for n in names:
            target = os.path.join(out_dir, os.path.basename(n))
            with zf.open(n) as src, open(target, "wb") as dst:
                dst.write(src.read())
            paths.append(target)
    return paths


class DialogueAudio:
    """Loads one dialogue chunk and precomputes a coarse RMS envelope for lip-sync."""

    def __init__(self, path: str, envelope_fps: int = 30):
        self.segment = AudioSegment.from_file(path).set_channels(1)
        self.duration_sec = len(self.segment) / 1000.0
        samples = np.array(self.segment.get_array_of_samples()).astype(np.float32)
        if len(samples) == 0:
            self.envelope = np.zeros(1)
        else:
            samples /= max(1.0, np.max(np.abs(samples)))
            window = max(1, int(self.segment.frame_rate / envelope_fps))
            n_windows = max(1, len(samples) // window)
            trimmed = samples[: n_windows * window]
            self.envelope = np.sqrt(np.mean(trimmed.reshape(n_windows, window) ** 2, axis=1))
        self.envelope_fps = envelope_fps

    def amplitude_at(self, local_time_sec: float) -> float:
        if local_time_sec < 0 or local_time_sec > self.duration_sec:
            return 0.0
        idx = int(local_time_sec * self.envelope_fps)
        idx = min(idx, len(self.envelope) - 1)
        return float(self.envelope[idx])


def build_combined_audio_track(chunk_paths: list, start_times: list, total_duration_sec: float, out_path: str):
    base = AudioSegment.silent(duration=int(total_duration_sec * 1000) + 500)
    for path, start in zip(chunk_paths, start_times):
        seg = AudioSegment.from_file(path)
        base = base.overlay(seg, position=int(start * 1000))
    base.export(out_path, format="wav")
    return out_path


def amplitude_to_mouth_shape(amp: float) -> str:
    if amp < 0.06:
        return "mouth_shape_1"
    if amp < 0.18:
        return "mouth_shape_2"
    if amp < 0.35:
        return "mouth_shape_3"
    return "mouth_shape_4"
