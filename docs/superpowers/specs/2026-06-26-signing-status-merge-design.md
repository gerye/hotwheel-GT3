# 设计:合并赛车「状态 + 合约」为单一签约状态

## 背景与目标
当前赛车有两个互相关联的字段:**状态**(`CarStatus`:未签约 / 现役 / 退役)与**合约**(`ContractType`:长期 / 短期)。合约只在「现役」时有意义,二者表达的是同一件事的不同侧面,存在冗余且容易不一致。

本设计把它们**合并为单一签约状态**,共 4 个值:

```
未签约 / 长期合约 / 短期合约 / 退役
```

「现役」不再是独立状态,而是「长期合约 或 短期合约」的统称。`ContractType` 枚举与 `Car.contract` 字段一并移除,彻底消除冗余。

## 数据模型
- `CarStatus`(`app/enums.py`)改为 4 值:`UNSIGNED=未签约`、`LONG=长期合约`、`SHORT=短期合约`、`RETIRED=退役`。
- 新增辅助:`CarStatus.is_active`(返回 `self in {LONG, SHORT}`)与模块常量 `ACTIVE_STATUSES = (LONG, SHORT)`。
- **删除 `ContractType` 枚举**;**从 `Car` 模型移除 `contract` 字段**。SQLite 里的旧 `contract` 列保留不读(SQLite 不便删列,留着无害)。
- 不变量(沿用):**无车队 ⟺ 未签约;有车队 ⟺ 长期/短期/退役**。

## 状态机(`cars.change_status`)
按目标状态:
- **→ 未签约**:任意状态都可;移出车队(`team_id=None`)。
- **长期 ⇄ 短期**:已在车队,直接切换合约类型(名额数不变,无需容量校验)。
- **长期/短期 → 退役**:仅现役可退役。
- **退役 → 长期/短期(复出)**:校验该类别现役名额未满(`check_active_capacity`),由调用方传入目标合约(长/短)。
- **未签约 → 长期/短期**:**禁止直接转**(必须先通过表单加入车队)。

## 受影响的「现役」判断(逐处改为 `状态 ∈ {长期,短期}`)
- 厂商车队成员品牌 / 每类别 ≤ 2 现役容量校验(`teams.check_can_assign` / `check_active_capacity` / `active_count`)。
- 专业赛参赛资格「仅现役」(`tournament.create_race`)。
- 车队出战车手 `_team_cars`(`tournament`)。
- 转会市场:`committed_salary` / `_active_in_category` 等按现役统计(`market`)。
- 其它查询里出现的 `Car.status == CarStatus.ACTIVE` 一律换成 `Car.status.in_(ACTIVE_STATUSES)`。

## 转会市场(`market`)
- **开盘释放**:把「短期合约」车释放为未签约(原逻辑按 `contract==SHORT`,改为 `status==SHORT`);长期合约留任。
- **签约 / 加入车队**:动作时选择长期或短期,直接落为对应状态(原独立的「合同」选择器并入)。

## 创建 / 编辑赛车(`cars.create_car` / `update_car` / 路由 / 表单)
- 表单去掉独立的「合同」选择器。
- 选「无车队」→ 未签约;选某车队 → 需同时给出长期/短期,落为对应状态(经 `check_can_assign` 校验)。
- `_car_rows` 状态下拉、`car_detail`、`team_detail`、`market.html`、`races.html` 等显示同步为 4 值。

## 数据迁移(`db.py`,原始 SQL,放进现有 backfill,跨机一次性生效)
状态按枚举**名字**存储。新增/重命名成员后,旧值 `'ACTIVE'` 无法被新枚举解析,故需在 ORM 读取前用原始 SQL 迁移:

```sql
UPDATE car SET status='LONG' WHERE status='ACTIVE';
```

即:**现有现役车 → 长期合约**;未签约 / 退役保持不变(符合「仅现役车→长期」的决定)。旧 `contract` 列不再使用。

## 测试
- 更新现有用例:去掉 `contract` 参数 / 断言。
- 新增:
  - 长期 ⇄ 短期 互切。
  - 退役 → 复出 选长/短(含名额满时拒绝)。
  - 开盘只释放短期合约、保留长期合约。
  - 未签约不能直接转为签约状态(须先加入车队)。
  - 容量 / 专业赛资格 / 品牌校验对长期、短期一视同仁(都算现役)。

## 取舍
彻底删除 `contract` 字段(消除冗余,符合目标)。备选是保留 `contract` 列只读不写——冗余仍在,不采用。
