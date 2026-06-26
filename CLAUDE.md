# CLAUDE.md — hotwheel-GT3

## 项目是什么
为家中风火轮(Hot Wheels)实体跑道(4 条赛道)搭建的**本地网页应用**:登记赛车/车队、组织并记录比赛、维护赛季荣誉(车队积分 + 赛车 MMR)。
本地运行,手机同 WiFi 可访问录入,界面响应式。

## 权威设计文档
完整需求与设计见 [docs/superpowers/specs/2026-06-22-hotwheel-gt3-design.md](docs/superpowers/specs/2026-06-22-hotwheel-gt3-design.md)。
增量设计另见 `docs/superpowers/specs/` 下:转会市场(2026-06-25)、签约状态合并(2026-06-26)。
**任何实现都以这些文档为准;改需求先改文档。**(注:转会市场 spec 里的 `Car.contract`/`ContractType` 已被「签约状态合并」取代——合约即状态,见下。)

## 环境约束(重要)
- **目标运行环境 Python 3.9**(Mac 上只有系统 3.9.6)。**每个 `.py` 模块第一行必须是 `from __future__ import annotations`**(代码用了 3.10+ 的 `X | None` 写法,延迟注解才能在 3.9 跑)。SQLModel 表模型一律用 `Optional[...]`。`pyproject.toml` 的 `requires-python` = `>=3.9`。
- **Windows 开发机**:原先没装真 Python(`python`/`python3` 是 Microsoft Store 的 0 字节假 stub)。已用 `winget install Python.Python.3.12` 装好,虚拟环境在 `.venv/`,优先用 `py -3` 或 `.venv/Scripts/python.exe`(别直接用 `python`,可能命中 Store stub)。
- **`start.bat` 必须是 CRLF + UTF-8 无 BOM**(LF 会让 cmd 解析错乱报一堆"不是内部命令")。已用 `.gitattributes`(`*.bat eol=crlf`)固定。

## 技术栈
- 存储:SQLite(`data/hotwheel.db`)+ 图片文件夹(`data/images/`)
- 后端:Python FastAPI + SQLModel + Uvicorn
- 前端:Jinja2 模板 + HTMX(无构建)+ 少量原生 JS/CSS,响应式
- 测试:pytest + FastAPI TestClient
- 启动:开发用 `uvicorn app.main:app`;给用户用一键启动 `start.bat`(Windows)/ `start.command`(Mac)——自动杀旧服务、起服务、开浏览器,网页页脚有手机扫码二维码(`/qr.png` + `app/netutil.access_url`)。
- 个人页/赛季页等按模板实时生成,不预存

## 三大功能块
1. **赛车与车队数据库**:统一列表页(标签切换、全局搜索全字段、筛选、新增/编辑)+ 实时生成的个人页。
2. **赛事系统**:开始比赛 → 勾选参赛车 → 随机分组(可视化)→ 4 道站位安排(每车遍历每道)→ 录入结果(5/3/2/1,未完赛0)→ 晋级/重组 → 回退。赛制:单人锦标赛、车队锦标赛。
3. **荣誉系统**:赛季管理、车队积分(赛季制清零)、赛车 MMR(按等级、赛季+历史双天梯、Elo 算法 K=24)。
4. **转会市场/经济**:赛季之间按上赛季表现给车队**预算**、给赛车**薪资**,半自动「选秀」在预算内重组阵容(见下「转会市场/经济」)。

## 关键规则(易错点)
- 赛车昵称唯一;铸模可重复;不做铸模唯一约束。
- **赛车状态:未签约 / 长期合约 / 短期合约 / 退役**(`CarStatus`)。**现役 = 长期合约 或 短期合约**(`is_active`/`ACTIVE_STATUSES`)。铁律:无车队⟺未签约,有车队⟺现役(长期/短期)或退役。
  - 加入车队→落具体合约(长期/短期);移出车队→未签约;长期⇄短期、现役⇄退役由状态控件切换。
  - **不能直接从未签约→现役**(须先加入车队);退役→复出(落具体合约)需车队现役名额未满。
  - 专业赛仅限**现役(长期/短期)**;表演赛任何状态都可。
- 厂商车队成员品牌必须一致;**例外:品牌为「无」(空/「无」)的车视为通用车,任何厂商队都可签约/考虑,签约后品牌仍为「无」**(`teams.is_brandless`)。**每车队每类别最多 2 个现役**(退役不占名额,可有多个退役)—— 设置/变更车队时即时校验。
- 车队命名:**宏观名**(`Team.name`,如法拉利车队)用于榜单/列表;**具体名**(分等级,厂商=品牌+别名+类别+车队;独立=宏观名+别名+类别)用于赛车页/具体比赛。别名按等级存(alias_f1/gt3/road),只在车队页改。见 `Team.specific_name(category)`。
- 分组铁律:每组 3-4 辆,绝不少于 3;偶数组不强求(10→4/3/3→晋级6→3/3→4 决赛组)。
- **并列裁决**:每组前 2 名晋级;名额边界并列时,按**空出的名额数**选晋级者(第 1 名也并列时要选 2 名,不是只选 1)——见 `scoring.resolve_advancement` 的 `slots`、`TieBreak.winner_car_ids`。
- 锦标赛收敛到最后一组(3-4 辆)时,该组 4 场直接定名次。
- 车队锦标赛:每组 2 个车队;1车队对2车队时 1 车积分×2;并列加赛 4 轮。
- MMR 仅专业赛改变,每个小组 4 场后结算;赛季 MMR 赛季末重置回 1500,历史 MMR 永不重置;初始 1500。
- 车队积分(现规则,见 `team_points.py`/`config`):**每次小组赛晋级 +1**,决赛圈**冠/亚/季 +4/+2/+1**;**车队锦标赛全部 ×2**;各等级叠加;仅专业赛;赛季制清零;记录来源。(旧的 +5/4/3、+10/8/6 已废弃。)

## 转会市场/经济(关键规则)
- **合约即状态**:长期合约/短期合约就是签约状态(已并入 `CarStatus`,无独立 `contract` 字段)。长期=转会窗口不释放;短期=开盘解约入自由池;自由市场签下默认短期。
- **预算**(整队一个池,覆盖全队现役薪资):`budget = 800 + 20×上赛季车队积分 + 50×单人赛夺冠 + 100×车队赛夺冠`。长期合同是硬支出,仅长期就超预算则保留长期车、签不了新人。
- **薪资**(单车,有下限不为负):`salary = max(30, 100 + MMR分量 + 100×夺冠 + 40×进决赛圈未夺冠 + 100×名宿)`;MMR分量:≥1500 `+(MMR−1500)×1`,<1500 `−(1500−MMR)×0.5`;**名宿**=本类别**历史 MMR 前 10%**。常数全在 `app/config.py`。
- **易错(已修)**:预算/薪资里的「夺冠/进决赛圈」**只统计 `status=已结束` 的比赛**;`racestats` 对未结束比赛不返回冠军/名次,否则进行中的比赛会虚增预算与薪资。
- 转会为**半自动选秀**:赛季结束→下季开启之间触发;释放短期→按「余额最高的队先签满」推荐→用户增删改→定档。每类别 **0 或 2 现役**;退役车不入市、不计薪资、不占名额。

## 推荐实现顺序
数据层 → 数据库页面 → 赛事流程(先单人后车队)→ 荣誉系统。用户要求全部做完,此为落地顺序。

## 跨机同步与 git 工作流
- 远程仓库 `origin` = https://github.com/gerye/hotwheel-GT3,在 Mac 与这台 Windows 之间同步。
- **数据也纳入版本库**:`data/hotwheel.db`(赛车/车队/比赛/积分/MMR/赛季全在这一个文件里)与 `data/images/` 都跟踪;`.gitignore` 只排除 `*.bak` 和 SQLite 运行时临时文件(`-wal/-shm/-journal`)。`.venv/`、`pic/`、`.claude/settings.local.json` 不入库。
- **铁律:数据库是二进制、无法合并**。务必「一台机器一次、开工先 `pull`、收工后 `push`」;两台都改了没先同步就会产生 `hotwheel.db` 冲突,只能二选一丢一边。
- `.claude/settings.json` 配了 SessionStart 钩子,启动自动 `git pull --ff-only`。预览配置在 `.claude/launch.json`。

## 技术注意点(踩过的坑)
- **Starlette 1.x**:`TemplateResponse` 用新签名 `TemplateResponse(request, "x.html", {ctx})`,旧式 `(name, ctx)` 已失效(会报 `unhashable type: 'dict'`)。
- **静态挂载顺序**:`/static/uploads` 必须挂在 `/static` 之前,否则上传图片 404(见 `app/main.py`)。
- 车子图片点击放大(灯箱)由 `base.html` 全局事件委托实现,监听所有 `/static/uploads/` 图片,新增展示处自动覆盖。

## 工作流程
- 实现前用 superpowers:writing-plans 出实现计划。
- 文档语言:中文。
