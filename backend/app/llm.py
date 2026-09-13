"""
Per-dialogue animation choreography — exactly one LLM call per dialogue line.
Tries DeepSeek's official API first, falls back to a Hugging Face-hosted model,
and finally to a deterministic heuristic so the pipeline never breaks without API keys.
"""
import json
import re
import requests

from app import config

VALID_MODES = {"idle", "talk", "wave", "point"}
VALID_RIGHT_HAND = {"right_hand_sword", "right_palm_1", "right_palm_2"}
VALID_LEFT_HAND = {"left_palm_3_cup", "left_palm_1", "left_palm_2"}
VALID_CAMERA = {"two_shot", "close_up_speaker", "wide_room", "dramatic_zoom"}

PROMPT_TEMPLATE = """You are a 2D cartoon animation director. A character named "{character}" \
speaks this line (may be in Hindi): "{line}"
Emotion hint: {emotion}
Genre: {genre}

Choose the best animation choreography for this single line and reply with ONLY compact JSON, no prose:
{{"mode": one of ["idle","talk","wave","point"],
"rightHand": one of ["right_hand_sword","right_palm_1","right_palm_2"],
"leftHand": one of ["left_palm_3_cup","left_palm_1","left_palm_2"],
"cameraShot": one of ["two_shot","close_up_speaker","wide_room","dramatic_zoom"]}}
"""


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object found in LLM response")
    return json.loads(match.group(0))


def _sanitize(data: dict) -> dict:
    mode = data.get("mode") if data.get("mode") in VALID_MODES else "talk"
    right_hand = data.get("rightHand") if data.get("rightHand") in VALID_RIGHT_HAND else "right_hand_sword"
    left_hand = data.get("leftHand") if data.get("leftHand") in VALID_LEFT_HAND else "left_palm_3_cup"
    camera = data.get("cameraShot") if data.get("cameraShot") in VALID_CAMERA else "two_shot"
    return {"mode": mode, "rightHand": right_hand, "leftHand": left_hand, "cameraShot": camera}


def _try_deepseek(prompt: str) -> dict:
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    resp = requests.post(
        config.DEEPSEEK_API_URL,
        headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": config.DEEPSEEK_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "max_tokens": 150,
        },
        timeout=20,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _extract_json(content)


def _try_huggingface(prompt: str) -> dict:
    if not config.HF_TOKEN:
        raise RuntimeError("HF_TOKEN not set")
    resp = requests.post(
        config.HF_API_URL,
        headers={"Authorization": f"Bearer {config.HF_TOKEN}", "Content-Type": "application/json"},
        json={
            "model": config.HF_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "max_tokens": 150,
        },
        timeout=30,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _extract_json(content)


def _heuristic(character: str, line: str, emotion: str) -> dict:
    text = f"{line} {emotion or ''}".lower()
    if any(k in text for k in ["surprised", "अरे", "wow", "shocked"]):
        mode, camera = "point", "close_up_speaker"
    elif any(k in text for k in ["happy", "khush", "hansi", "welcome", "?" ]):
        mode, camera = "wave", "two_shot"
    elif any(k in text for k in ["curious", "kaisa", "kyun", "kya"]):
        mode, camera = "talk", "close_up_speaker"
    else:
        mode, camera = "talk", "two_shot"
    return {"mode": mode, "rightHand": "right_palm_1", "leftHand": "left_palm_3_cup", "cameraShot": camera}


def get_choreography(character: str, line: str, emotion: str, genre: str) -> dict:
    prompt = PROMPT_TEMPLATE.format(character=character, line=line, emotion=emotion or "neutral", genre=genre or "general")

    for attempt in (_try_deepseek, _try_huggingface):
        try:
            return _sanitize(attempt(prompt))
        except Exception:
            continue

    return _sanitize(_heuristic(character, line, emotion))
