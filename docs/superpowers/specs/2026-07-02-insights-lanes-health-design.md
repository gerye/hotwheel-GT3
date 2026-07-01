# 统计/诊断:赛道公平性 + 健康自检 设计文档

> 状态:已与用户在 brainstorming 中逐节确认(2026-07-02)。实现前的权威设计。
> 关系:纯新增只读页面,不改动现有数据模型与业务逻辑。复用 `HeatResult`(lane/rank/dnf)、`Race`(status/season/category)、`Car`/`Team` 现有字段与既有校验口径。

## 1. 目标
把「已躺在库里但没展示」的数据变成两页可看的价值,均**只读**、不改库:
- **赛道公平性**(`/lanes`):量化实体 4 道跑道的物理偏差(哪条道更快 / 更爱把车甩飞)。
- **健康自检**(`/health`):一眼看出真实库有没有违反项目铁律的脏数据,链到现场手动改。

## 2. 架构
- 新增只读聚合服务 `app/services/insights.py`(纯查询,无写操作)。
- 新增路由 `app/routers/insights.py`:hub `/insights` + `/lanes` + `/health`,在 `app/main.py` 注册。
- 模板:`insights.html`(hub,两张卡片)、`lanes.html`、`health.html`。
- 导航:`base.html` 顶栏加一个「统计」→ `/insights`(保持顶栏简洁;两报告从 hub 进)。
- 常数集中在 `app/config.py`:`LANE_MIN_SAMPLE`、`LANE_BIAS_THRESHOLD`。

## 3. 赛道公平性 `/lanes`

### 3.1 数据源与筛选
- 取所有 **`Race.status == FINISHED`** 比赛的 `HeatResult`(join `Heat → Group → RaceRound → Race`)。
- 可选筛选(GET 参数,缺省=全部):`season_id`(`Race.season_id`)、`category`(`Race.category`)。
- 赛道偏差是物理属性、与车型/类别无关,故默认汇总全部以求最大样本;筛选仅供下钻。

### 3.2 每条道(1–4)的指标
对某筛选下、落在该道的全部 `HeatResult`(记为该道的「出场」):
- **场次 n**:该道出场数(3 车组不产生 4 道数据,故各道 n 可不同)。
- **平均名次 `avg_rank`**:只在**完赛**结果(`dnf=False` 且 `rank` 非空)上取 `rank` 的均值;越小越快;该道无完赛结果则为 `None`。
- **脱轨率 `dnf_rate`**:该道 `dnf=True` 占比 = dnf 数 / n(把「慢的道」与「爱甩飞车的道」分开)。
- **拿第一比例 `win_rate`**:该道 `rank==1` 占比 = 第一数 / n。

### 3.3 判定(verdict)
- 只在**样本足够**的道之间比较:仅纳入 `n >= LANE_MIN_SAMPLE`(默认 10)且 `avg_rank` 非空的道。
- `spread = max(avg_rank) − min(avg_rank)`(纳入的道之间)。
- `spread >= LANE_BIAS_THRESHOLD`(默认 0.5)→ 提示「疑似偏差:最快道 X 道 vs 最慢道 Y 道」;否则「未见明显偏差」。
- 任一道 `n < LANE_MIN_SAMPLE` → 该道标注「样本不足,仅供参考」;全部样本不足则整体提示样本不足。

### 3.4 返回结构
`lane_stats(session, *, season_id=None, category=None) -> dict`:
```
{
  "lanes": [ {"lane": 1, "n": int, "avg_rank": float|None,
              "dnf_rate": float, "win_rate": float, "low_sample": bool}, ... ],  # 1..NUM_LANES
  "total_results": int,
  "verdict": {"biased": bool|None, "spread": float|None,
              "fastest_lane": int|None, "slowest_lane": int|None,
              "enough_sample": bool},
}
```

### 3.5 页面
- 顶部:赛季 / 类别筛选下拉(提交走 GET);一行 verdict 文案。
- 一张 4 行表:道号 · 场次 · 平均名次 · 脱轨率 · 拿第一%;`avg_rank` 为 `None` 显示「—」,`low_sample` 行加淡色「样本不足」标注。
- 一条平均名次的简易横向条形对比(道间可视),纯 CSS/内联,无 JS 依赖。

## 4. 健康自检 `/health`(只读)

### 4.1 概览计数
`overview_counts(session) -> dict`:`{cars, teams, active, retired, unsigned, seasons}`(信息性,非问题)。

### 4.2 检查项
`health_checks(session) -> list[dict]`,每项:
```
{"key": str, "title": str, "severity": "error"|"warn", "ok": bool,
 "items": [ {"label": str, "href": str} ]}   # ok=True 时 items 为空
```

**错误级(违反铁律)**
1. `status_consistency` —— 有车队却 `未签约`,或无车队却 `现役/退役`(违反 无车队⟺未签约)。链到 `/cars/{id}`。
2. `capacity` —— 某车队某类别现役 > `MAX_CARS_PER_CATEGORY`(2)。链到 `/teams/{id}`。
3. `brand_mismatch` —— 厂商车队的现役成员品牌非「无」且 ≠ 队品牌(复用 `teams.is_brandless`)。链到 `/cars/{id}`。

**提醒级(未必错,值得注意)**
4. `unfinished_races` —— 存在 `Race.status == IN_PROGRESS`(可能忘了推进/回退)。链到 `/races/{id}`。
5. `open_draft` —— 存在未定档的 `MarketDraft`(开着盘没结束)。链到 `/market`。

### 4.3 页面
- 顶部概览计数一行。
- 每个检查一张卡片:✅ 通过 / ❌ + 问题清单(每条一个可点链接);错误级红、提醒级黄。
- 全部通过时页面顶部显示「✅ 一切正常」。

## 5. 服务边界与文件
- `app/services/insights.py`:`lane_stats`、`health_checks`、`overview_counts` —— 全部只读、无 `session.add/commit`。单一职责:聚合与诊断查询。
- `app/routers/insights.py`:三个 GET 路由,渲染模板;`/lanes` 读 `season_id`/`category` 查询参数并传下拉选项(赛季列表、`Category` 列表)。
- 模板:`insights.html`/`lanes.html`/`health.html`,沿用 `.card`/`.row`/`.tag` 与 Starlette 1.x `TemplateResponse(request, "x.html", {ctx})`。
- `app/config.py` 增 `LANE_MIN_SAMPLE = 10`、`LANE_BIAS_THRESHOLD = 0.5`。
- `app/main.py` 注册 `insights.router`;`base.html` 顶栏加「统计」。

## 6. 测试要点(`tests/test_insights.py`)
- `lane_stats`:构造已知 lane/rank/dnf 的若干 `HeatResult`(直接建模型或跑一场小比赛),验证各道 `n`/`avg_rank`(只算完赛)/`dnf_rate`/`win_rate`;`season_id`/`category` 筛选生效;未结束比赛的 heat **不计入**。
- verdict:构造明显偏差(某道平均名次显著更小)→ `biased=True` 且 `fastest_lane` 正确;样本不足 → `enough_sample=False`。
- `health_checks`:分别塞入 5 类问题各一,断言对应项 `ok=False` 且 `items` 命中;库干净时全部 `ok=True`。
- `overview_counts`:计数正确。
- 路由:`/insights`、`/lanes`(含带筛选参数)、`/health` 返回 200 且含关键文本。

## 7. 边界与约定
- 全程只读:任何函数不得写库(评审须核查无 `add/commit`)。
- DNF 定义:`HeatResult.dnf=True`(未完赛);其 `rank` 通常为空,不进 `avg_rank`,只进 `dnf_rate`。
- 3 车组:只产生 1–3 道的 `HeatResult`,4 道该场次不计;各道独立按各自 n 统计。
- 空库/无比赛:`lane_stats` 各道 n=0、`avg_rank=None`、verdict `enough_sample=False`;页面显示「暂无数据」。
- 昵称唯一由 DB 约束保证,不单列检查(YAGNI)。

## 8. 暂不做(YAGNI)
- 一键修复(本期只读;修复走现有车/队页面)。
- 站位公平性的主动纠偏 / 按赛道偏差调整站位算法。
- 图表库 / 前端构建(条形用内联 CSS)。
- 赛道偏差的统计显著性检验(只给样本量提示,不做 p 值)。
