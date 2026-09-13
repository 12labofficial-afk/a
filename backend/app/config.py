import os

DATA_DIR = os.environ.get("DATA_DIR", "/data")
JOBS_DIR = os.path.join(DATA_DIR, "jobs")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

HF_TOKEN = os.environ.get("HF_TOKEN", "")
HF_MODEL = os.environ.get("HF_MODEL", "deepseek-ai/DeepSeek-V3-0324")
HF_API_URL = os.environ.get("HF_API_URL", f"https://router.huggingface.co/v1/chat/completions")

VIDEO_WIDTH = int(os.environ.get("VIDEO_WIDTH", "1280"))
VIDEO_HEIGHT = int(os.environ.get("VIDEO_HEIGHT", "720"))
VIDEO_FPS = int(os.environ.get("VIDEO_FPS", "24"))

os.makedirs(JOBS_DIR, exist_ok=True)
