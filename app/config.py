from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "hotwheel.db"

NUM_LANES = 4          # 跑道数
INITIAL_MMR = 1500.0   # 初始 MMR
MAX_CARS_PER_CATEGORY = 2  # 每车队每类别最多车数


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    IMAGES_DIR.mkdir(exist_ok=True)
