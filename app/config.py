from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "hotwheel.db"

NUM_LANES = 4          # 跑道数
INITIAL_MMR = 1500.0   # 初始 MMR
MAX_CARS_PER_CATEGORY = 2  # 每车队每类别最多车数

ELO_K = 24.0

# 车队积分(新规则用,见 team_points.py)
TP_ADVANCE = 1          # 每次小组赛晋级
TP_PODIUM = {1: 4, 2: 2, 3: 1}   # 冠/亚/季额外
TP_TEAM_MULTIPLIER = 2  # 车队赛全部 ×2
# 预算
BUDGET_BASE = 800
POINT_VALUE = 20        # 每 1 车队积分 → 预算
CHAMP_BUDGET_SOLO = 50
CHAMP_BUDGET_TEAM = 100
# 薪资
SALARY_BASE = 100
SALARY_FLOOR = 30
SALARY_MMR_UP = 1.0     # MMR≥1500 每分
SALARY_MMR_DOWN = 0.5   # MMR<1500 每分(折扣)
SALARY_CHAMP = 100      # 每个夺冠
SALARY_FINALS = 40      # 每次进决赛圈未夺冠
SALARY_LEGEND = 100     # 名宿费
LEGEND_TOP_PCT = 0.10   # 历史 MMR 本类别前 10% 为名宿

# 赛道公平性(insights)
LANE_MIN_SAMPLE = 10      # 某道场次 < 此数 → 样本不足,不纳入偏差判定
LANE_BIAS_THRESHOLD = 0.5 # 最快/最慢道平均名次差 ≥ 此值 → 提示疑似偏差


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    IMAGES_DIR.mkdir(exist_ok=True)
