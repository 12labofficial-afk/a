# AI Script → 2D Animation Studio

Ek Python/FastAPI backend jo tumhara script-JSON (dialogues + timeline + voice
assignments), uska audio-chunks ZIP, aur character rig (cutout body-part PNGs)
leke pura 2D lip-synced animation video khud bana deta hai — **har dialogue ke
liye ek AI (LLM) call** lagakar uski animation choreography (pose/gesture/camera)
decide karta hai, aur mouth-movement timing **actual audio waveform** se
(directly), na ki guesswork se.

## Kaise kaam karta hai

1. **Project JSON** — wahi format jisme `characterSettings`, `dialogues`,
   `timeline` (`startTime`/`duration` har dialogue ke liye), aur
   `voiceAssignments` hote hain.
2. **Audio ZIP** — timeline ke hisaab se tute hue per-dialogue audio chunks
   (naturally sorted filenames, e.g. `001.wav`, `002.wav`, ...).
3. **Characters ZIP** — har character-naam ka apna folder, andar cutout
   body-part PNGs: `body`, `head_eyes_opened`, `head_eyes_closed`,
   `mouth_shape_1..4`, `arm_left_upper`, `arm_right_upper`, `forearm_left`,
   `forearm_right`, `left_palm_*`/`right_palm_*` (ya `right_hand_sword`),
   `thigh_left`/`thigh_right`, `leg_lower_left`/`leg_lower_right`. Filenames
   fuzzy-matched hote hain (jaise "left_hand_open.png" bhi chal jaayega); ek
   single bade master-sheet atlas image (1024x1024 style) bhi upload kar sakte
   ho, wo auto-slice ho jaata hai.

Backend phir:
- Har dialogue ke liye **ek** LLM call karta hai (pehle DeepSeek API, fail ho
  to Hugging Face Inference API, fail ho to deterministic heuristic) — jisse
  us line ka body-gesture (idle/talk/wave/point), hand-prop, aur camera shot
  decide hota hai.
- Har dialogue ke audio chunk ka amplitude envelope nikaal ke uske exact
  start/duration window me mouth-shape (closed → wide-open) frame-by-frame
  select karta hai — matlab "itne second se itne second tak mouth on rahega"
  wahi audio se directly control hota hai.
- 2D forward-kinematics se character ke body parts ko rotate/position karke
  frame-by-frame Pillow me composite karta hai, phir ffmpeg se final MP4
  (video + timeline-aligned audio) bana deta hai.
- Frontend (simple HTML/JS) upload form + progress bar + final video player
  deta hai.

## Chalane ka tarika (Docker)

```bash
cp .env.example .env
# .env me DEEPSEEK_API_KEY ya HF_TOKEN me se koi ek daal do (dono optional
# hain — bina key ke bhi heuristic fallback se chal jaayega)

docker compose up --build
```

Fir browser me `http://localhost:8000` kholo, teeno files upload karo
(project JSON, audio ZIP, characters ZIP), aur "Animation Generate Karo"
dabao.

## Bina Docker ke local run

```bash
cd backend
pip install -r requirements.txt
# ffmpeg system me installed hona chahiye (apt install ffmpeg)
export DATA_DIR=/tmp/animation-data
uvicorn app.main:app --reload --port 8000
```

## API

- `POST /api/jobs` — multipart form: `project_json`, `audio_zip`,
  `characters_zip`, optional `width`/`height`/`fps`. Returns `{job_id}`.
- `GET /api/jobs/{job_id}` — status/progress polling.
- `GET /api/jobs/{job_id}/video` — final MP4 (ready jab `state == "done"`).

## Env vars (`.env`)

| Var | Matlab |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek ki official API key (pehli priority) |
| `HF_TOKEN` | Hugging Face Inference API token (fallback) |
| `HF_MODEL` | HF par kaunsa model use karna hai (default DeepSeek-V3) |
| `VIDEO_WIDTH`/`VIDEO_HEIGHT`/`VIDEO_FPS` | Output video settings |
