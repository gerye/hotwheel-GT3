# CLAUDE.md — hotwheel-GT3

家用风火轮(Hot Wheels)实体跑道(4 道)的**本地网页应用**:登记赛车/车队、组织记录比赛、维护赛季荣誉(车队积分 + 赛车 MMR)、赛季间转会。本地运行,手机同 WiFi 可录入,界面响应式。

## 常用命令
- 跑测试:`./.venv/bin/python -m pytest -q`(Windows 用 `.venv/Scripts/python.exe`)
- **全链路自检**:`./.venv/bin/python scripts/sim_selfcheck.py`(离线内存库,不碰真实库;有问题退出码 1)。**改完转会/赛事/荣誉逻辑后跑一次**。也可 `pytest --runslow`(默认 `pytest` 跳过这个 ~50s 的慢测)。
- 开发起服务:`./.venv/bin/python -m uvicorn app.main:app`
- 给用户一键启动:`start.bat`(Windows)/ `start.command`(Mac)——杀旧服务、起服务、开浏览器;页脚有手机扫码二维码(`/qr.png` + `app/netutil.access_url`)。

## 技术栈
SQLite(`data/hotwheel.db`)+ 图片(`data/images/`);FastAPI + SQLModel + Uvicorn;Jinja2 + HTMX(无构建)+ 少量原生 JS/CSS;pytest + TestClient。个人页/赛季页按模板实时生成,不预存。

## 环境铁律
- **运行环境 Python 3.9**(Mac 系统 3.9.6)。**每个 `.py` 首行必须 `from __future__ import annotations`**(代码用了 3.10+ 的 `X | None`,靠延迟注解在 3.9 跑);SQLModel 表模型一律 `Optional[...]`;`requires-python = ">=3.9"`。
- **Windows 开发机**:系统 `python`/`python3` 可能是 Microsoft Store 的 0 字节假 stub;用 `.venv/`,优先 `py -3` 或 `.venv/Scripts/python.exe`。
- **`start.bat` 必须 CRLF + UTF-8 无 BOM**(LF 会让 cmd 报一堆"不是内部命令");已由 `.gitattributes`(`*.bat eol=crlf`)固定。

## 权威文档(改需求先改文档)
- 主设计:[2026-06-22-hotwheel-gt3-design.md](docs/superpowers/specs/2026-06-22-hotwheel-gt3-design.md)。
- 增量:转会市场(2026-06-25)、签约状态合并(2026-06-26)、**转会选秀重构(2026-07-02,最新且权威)**。
- 已废弃细节:2026-06-25 的 `Car.contract`/`ContractType`(→ 合约即状态);其转会流程 §3/§4.1(→ 2026-07-02 选秀)。

## 四大功能块
1. **数据库**:统一列表页(标签切换、全字段搜索、筛选、增改)+ 实时个人页。
2. **赛事**:开赛→勾选参赛车→随机分组(可视化)→ 4 道站位(每车遍历每道)→ 录结果(5/3/2/1,未完赛 0)→ 晋级/重组→回退。赛制:单人锦标赛、车队锦标赛。
3. **荣誉**:赛季管理、车队积分(赛季清零)、赛车 MMR(按等级、赛季+历史双天梯、Elo K=24)。
4. **转会/经济**:赛季间按上季表现给车队预算、给车薪资,半自动选秀在预算内重组阵容。

## 关键规则(易错点)

### 赛车状态与车队(`CarStatus`)
- 四状态:未签约 / 长期合约 / 短期合约 / 退役。**现役 = 长期 或 短期**(`is_active` / `ACTIVE_STATUSES`)。
- 铁律:**无车队 ⟺ 未签约;有车队 ⟺ 现役或退役**。加入车队→落具体合约;移出→未签约;长期⇄短期、现役⇄退役由状态控件切换。
- **不能直接 未签约→现役**(须先加入车队);退役→复出需该队该类别现役名额未满。
- 专业赛仅限现役;表演赛允许未签约/现役;**退役车不参加任何比赛(含表演赛)**。退役也不占薪资(`market.committed_salary` 只算现役)。
- 厂商车队成员品牌须一致;**例外:品牌「无」(空/「无」)= 通用车,任何厂商队可签,签后品牌仍「无」**(`teams.is_brandless`)。
- **每车队每类别最多 2 现役**(退役不占名额,可多个退役);设置/变更车队时即时校验。

### 车队命名
- **宏观名**(`Team.name`,如「法拉利车队」)用于榜单/列表;**具体名**(分等级:厂商=品牌+别名+类别+车队;独立=宏观名+别名+类别)用于赛车页/具体比赛。别名按等级存(`alias_f1/gt3/road`),只在车队页改。见 `Team.specific_name(category)`。

### 赛事与分组
- 分组:每组 **3-4 辆,绝不少于 3**;偶数组不强求(10→4/3/3→晋级 6→3/3→4 决赛组)。
- **并列裁决**:每组前 2 晋级;名额边界并列时按**空出的名额数**选晋级者(第 1 名也并列则选 2 名,非只选 1)。见 `scoring.resolve_advancement` 的 `slots`、`TieBreak.winner_car_ids`。
- 收敛到最后一组(3-4 辆)时,该组 4 场直接定名次。
- **车队锦标赛**:每组 2 队;1 队对 2 队时 1 车积分 ×2;并列加赛 4 轮;**队数非 2 的幂时用轮空(bye)推进**(落单队直接晋级,`Group.team_b_id=None`、无 heat)。

### 荣誉
- **MMR**:仅专业赛改变,每小组 4 场后结算;赛季 MMR 赛季末重置回 1500,历史 MMR 永不重置;初始 1500;Elo K=24。
- **车队积分**(`team_points.py`/`config`):小组赛每次晋级 **+1**,决赛圈**冠/亚/季 +4/+2/+1**;**车队锦标赛全部 ×2**;各等级叠加;仅专业赛;赛季清零;记录来源。(旧 +5/4/3、+10/8/6 已废弃。)

## 转会市场/经济(`market.py` 经济计算 + `market_draft.py` 选秀流程)
- **合约即状态**:长期/短期即签约状态(并入 `CarStatus`,无独立字段)。长期=窗口不释放、锁死原队;短期=可被挖角 / 进队时解约;自由市场签下默认短期。
- **预算**(整队一池,覆盖全队现役薪资):`800 + 20×上季车队积分 + 50×单人赛夺冠 + 100×车队赛夺冠`。长期是硬支出:仅长期就超预算 → 保留长期车、签不了新人。
- **薪资**(单车,下限 30):`max(30, 100 + MMR分量 + 100×夺冠 + 40×进决赛圈未夺冠 + 100×名宿)`;MMR分量:≥1500 `+(MMR−1500)×1`,<1500 `−(1500−MMR)×0.5`;**名宿 = 本类别历史 MMR 前 10%**。常数全在 `app/config.py`。
- **易错(已修)**:预算/薪资里的「夺冠/进决赛圈」**只统计 `status=已结束` 的比赛**(`racestats` 对未结束不返回名次),否则进行中的比赛虚增预算薪资。

### 选秀流程(2026-07-02 重构;不再一刀切释放)
- 优先级:按「假设各队维持现有阵容」的**余额**降序(平局:车队积分 → 最高 MMR 车 → 固定种子随机);**逐队处理,每确认一队后重算队列**(挖角抬升被挖队余额)。
- **进当前队即自动解约其全部短期**(空出薪资);只解约当前队自己的。
- **含长期车的类别必须先锁**;每类别两下拉手动选(长期车服务端钉死一槽),候选池 = 自由身 + 未确认队短期(挖角);建议(保持/解散/补强)仅供参考。
- **每类别现役数**:满 2 或空 0 恒合法;**含长期车**类别须补满 2,除非池中已无「合法+买得起」的车才允许停 1(逃生阀);**无长期车**类别停在 1 仅当**买不起两辆最便宜的车**(或候选不足 2),否则必须 0 或 2。
- 逃生阀保证不死锁;两长期类别争预算由玩家取舍。`MarketDraft`/`DraftCarSnapshot` 存草稿状态,支持锁定集合与**一键重置**。退役车全程不入市、不计薪资、不占名额。

## 跨机同步与 git
- `origin` = https://github.com/gerye/hotwheel-GT3,Mac ↔ Windows 同步。
- **数据入库**:`data/hotwheel.db`(赛车/车队/比赛/积分/MMR/赛季全在此一文件)与 `data/images/` 都跟踪;`.gitignore` 只排 `*.bak` 和 SQLite 临时文件(`-wal/-shm/-journal`);`.venv/`、`pic/`、`.claude/settings.local.json` 不入库。
- **铁律:DB 是二进制、无法合并**——「一机一次、开工先 `pull`、收工后 `push`」;两机都改没先同步就冲突,只能二选一。
- **改了模型/加了列**:首次跑真实库时 `db.sync_schema` 自动加列/加表;**别把 schema 迁移后的 `data/hotwheel.db` 随代码提交**(提交前 `git checkout -- data/hotwheel.db`)。
- SessionStart 钩子(`.claude/settings.json`)启动自动 `git pull --ff-only`;预览配置在 `.claude/launch.json`。

## 踩过的坑
- **Starlette 1.x**:`TemplateResponse(request, "x.html", {ctx})`(新签名);旧式 `(name, ctx)` 报 `unhashable type: 'dict'`。
- **静态挂载顺序**:`/static/uploads` 必须挂在 `/static` 之前,否则上传图 404(`app/main.py`)。
- 图片点击放大(灯箱)由 `base.html` 全局事件委托实现,监听所有 `/static/uploads/` 图,新增处自动覆盖。

## 工作流程
- 实现前用 superpowers:writing-plans 出计划(较大改动)。文档语言:中文。
- 改逻辑后跑 `pytest`(快)+ `scripts/sim_selfcheck.py`(或 `pytest --runslow`)。
