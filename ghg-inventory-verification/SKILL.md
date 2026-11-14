---
name: ghg-inventory-verification
description: 依据 GHG Protocol 与 ISO 14064 完成组织温室气体排放核算与核查。当用户提供一个报告年内 Scope 1/2/3 的活动数据与凭证（能源发票、外购电力发票、上下游运输、采购、差旅、通勤、问卷等），要求计算 tCO2e、生成温室气体排放核查清册、或生成温室气体计算报告与第三方核查报告时触发。包含可插拔凭证抽取、人工确认闸、方法与排放因子匹配、带公式 xlsx 清册、中英双模式报告、勾稽校验与交付打包。组织边界、报告年、实体清单、排放因子库、方法学与保证等级全部由运行时配置注入。
description_en: Organization-level GHG inventory and verification per GHG Protocol and ISO 14064. Triggered when a user supplies one reporting year of Scope 1/2/3 activity data and vouchers and asks for tCO2e calculation, a GHG inventory workbook, an organizational GHG report, or a third-party verification report. Covers voucher extraction, a human confirmation gate, method and factor matching, a formula-driven xlsx inventory, bilingual dual-mode reports, reconciliation checks and delivery packaging.
agent_created: true
---

# 组织温室气体排放核算与核查

## 目的与适用范围

本 Skill 把「原始凭证 → 活动数据 → 方法与排放因子 → tCO2e → 排放核查清册 → 核查报告」变成一条可复现、可追溯、可校验的流水线。计算核心只接受已签核的标准化活动数据台账；清册为带公式的 xlsx；报告按模式 A（组织排放/计算报告，ISO 14064-1 + GHG Protocol）或模式 B（第三方核查，ISO 14064-3）输出中英各一份。

适用：组织层级的温室气体盘查、核算、内部核查、第三方核查底稿准备、历史清册重算与口径复核。

不适用（命中即退出并向用户说明原因）：
- 要求把某具体企业的名称、历史因子、上年结果或固定年份内置进本 Skill；
- 在无人签核的情况下要求正式核查声明、保证结论或核查意见；
- 产品级 LCA、项目级减排量、碳足迹标签、碳中和抵消等非组织盘查任务；
- 仅需编辑一份既有 xlsx（改用表格编辑类 Skill）；
- 输入既非标准化台账也非受支持的凭证类型，且拒绝人工补录。

## ⛔ 硬性规则

1. **纯抽象，零企业数据**：包内不得写入任何真实组织名、人名、地址、真实排放因子数值、真实报告年份或真实报告文字。所有值来自运行时 `org_config.json` / `activity_ledger.json` / `factor_library.json`。运行 `ghg audit` 确认。
2. **人工确认闸不可绕过**：`activity_ledger.json` 每行必须带非空 `confirmation.signed_by` 与 `signed_at`。存在未签核行时，Stage 5 计算必须硬拒绝，不得跳过、不得代签、不得用默认值填空。
3. **不伪造核查结论**：模式 B 的保证等级、实质性、核查程序记录、核查员与核查声明必须由授权人输入并签核。无签核只生成 `*_draft.docx`，结论段保留占位符。任何路径都不得由模型推断或补写保证结论。
4. **不用启发式取合计**：禁止「合计行取行内最大数值」「取某列最大值」「沿用上年值」等做法。所有合计由显式字段计算并经 Stage 7 勾稽规则验证。
5. **不硬编码量纲除数**：统一公式 `tco2e = ad * ef * gwp / scale`，`scale` 必须由因子库的单位契约显式给出。禁止在计算代码里写常量分母。
6. **公式版清册零错误才交付**：公式写字符串、不写死值；清除外链；重算结果与纯函数结果双轨对账；任何 ERROR 阻断交付。
7. **动态数值只进表格单元格**：报告散文使用 `assets/phrases.json` 的固定话术，数值只填表格占位符，使中英数值可逐项对账。
8. **不擅自选因子或方法**：一源多因子、方法歧义、单位歧义、期间歧义一律产出候选集上报人工，不静默取值、不静默填 0。

## 资源索引

| 资源 | 何时读取 | 定位方式 |
|---|---|---|
| `references/standards.md` | 判定范围/类别、ISO 条款映射时 | `grep -n "S3-" references/standards.md` |
| `references/methodology.md` | 选择计算方法、S2 双口径、GWP、基准年重算时 | `grep -n "method\|scale\|recalc" references/methodology.md` |
| `references/schemas.md` | 组装或校验任何 JSON 时 | `grep -n "field\|required" references/schemas.md` |
| `references/inventory_layout.md` | 构建清册 sheet、写公式时 | `grep -n "anchor\|formula" references/inventory_layout.md` |
| `references/report_fields.md` | 生成报告、做字段映射时 | `grep -n "A\.\|B\." references/report_fields.md` |
| `references/validation_rules.md` | 执行 Stage 7 校验时 | `grep -n "ERROR\|WARN" references/validation_rules.md` |
| `references/legacy_mapping.md` | 仅开发期做原型抽象化对照时 | 通读，禁止把其中任何历史数据带入运行 |
| `assets/schemas/*.schema.json` | 结构校验（由 `validate_config.py` 自动加载） | 程序读取，无需载入上下文 |
| `assets/config_template.json` | 初始化一次运行 | 复制到 run 目录后填写 |
| `assets/factor_library_template.json` | 初始化因子库 | 复制到 run 目录后填写 |
| `assets/inventory_template.json` | Stage 6 建清册 | 程序读取 |
| `assets/report_layout.json` | Stage 8 章节与表格骨架 | 程序读取 |
| `assets/phrases.json` | Stage 8 中英固定话术 | 程序读取，CN/EN 键须一一对应 |
| `assets/schemas/verification_signoff.schema.json` | 模式 B 签核校验 | 程序读取 |
| `assets/schemas/pending_ledger.schema.json` | Stage 1 待确认台账结构 | 程序读取 |
| `assets/extraction_rules.json` | 凭证字段别名、期间正则、单位提示 | `grep -n "field_aliases\|period_patterns" assets/extraction_rules.json` |
| `scripts/extractors/` | 4 类可插拔凭证抽取器 | `scripts/cli.py extract` 自动分派 |

脚本经 `scripts/cli.py` 统一调用，无需载入上下文即可执行。

## 运行约定与实现状态

统一入口（Windows 使用 `Scripts/python.exe`）：

```
python scripts/cli.py <command> --config <org_config.json> --run-dir <输出目录>
```

| 命令 | 阶段 | M0 状态 |
|---|---|---|
| `deps` | 环境自检 | 可用 (M0) |
| `audit` | 纯抽象审计 | 可用 (M0) |
| `init` | Stage 0 配置校验 + run 目录初始化 | 可用 (M0) |
| `validate-skill` | 调用官方 quick_validate | 可用 (M0) |
| `classify` | Stage 3 排放源识别 | 可用 (M1) |
| `match` | Stage 4 方法与因子匹配 | 可用 (M1) |
| `compute` | Stage 5 计算引擎 | 可用 (M1) |
| `inventory` | Stage 6 公式版清册构建 | 可用 (M2) |
| `report` | Stage 8 中英双模式报告生成 | 可用 (M3) |
| `check` | Stage 7 勾稽校验（V01–V20 全部落地） | 可用 (M1–M5) |
| `deliver` | Stage 9 交付清单、证据索引与分发 zip | 可用 (M5) |
| `pipeline` | 一次跑完 Stage 3 → 4 → 5 → 6 → 8 → 7 → 9 | 可用 (M5) |
| `extract` | Stage 1 凭证抽取 → 待确认台账 | 可用 (M4) |
| `confirm` | Stage 2 人工确认闸 → 已签核台账 | 可用 (M4) |

**全部里程碑已完成**，`MILESTONE_OF_UNIMPLEMENTED` 为空。完整交付时 `checks.json` 的 `rules_deferred` 为空；缺清册或报告时对应规则自动回到 deferred，不静默跳过。

**Stage 1/2 刻意不纳入自动 pipeline**：中间必须有人签核。先手工执行 `extract` → 人工复核/补录 → `confirm`，再运行 `pipeline`。

未实现命令返回 `NOT_IMPLEMENTED` 与目标里程碑，不产生半成品文件。**禁止在未实现阶段手写临时脚本冒充流水线输出。**

### Run 目录约定（M1）

`pipeline --run-dir <dir>` 按固定文件名串联，可用同名参数覆盖：

| 文件 | 角色 |
|---|---|
| `org_config.json` | 运行时配置（可用 `--config` 覆盖） |
| `factor_library.json` | 运行时因子库 |
| `activity_ledger.json` | **已签核**的活动数据台账 |
| `classification.json` | Stage 3 输出 |
| `matched.json` | Stage 4 输出 |
| `results.json` | Stage 5 输出，`check` 会回写 `checks` |
| `ghg_inventory.xlsx` | Stage 6 公式版清册 |
| `formula_cache.json` | Stage 6 每个公式单元格的确定性期望值 |
| `report_A_zh.docx` / `report_A_en.docx` | 模式 A 中英报告 |
| `report_B_zh*.docx` / `report_B_en*.docx` | 模式 B 中英报告（无签核带 `_draft`） |
| `chart_scope_*.png` / `chart_category_*.png` | 内嵌图表 |
| `report_manifest.json` | 每份报告的字段快照、图表数据与护栏状态 |
| `verification_signoff.json` | 人工提供的模式 B 签核（可选，缺失即只出草稿） |
| `pending_ledger.json` | Stage 1 待确认台账（签核为空） |
| `confirm_check.json` | Stage 2 缺签/不完整清单与闸门结论 |
| `checks.json` | Stage 7 完整校验报告 |
| `evidence_index.json` | Stage 9 凭证与台账行的反向索引 |
| `delivery_manifest.json` | Stage 9 交付清单（角色、字节数、SHA-256、AIGC 声明） |
| `delivery/<run_id>_delivery.zip` | Stage 9 分发包 |

未签核台账会在 Stage 3/5 被硬拒绝；`compute --append --version-id V2 --status draft` 可追加版本，仅一个版本允许为 `final`。`check --skip-workbook` / `--skip-reports` 可分别跳过清册与报告校验，被跳过的规则会自动回到 `rules_deferred`，不静默省略。

## 环境与依赖自检

执行 `python scripts/cli.py deps`。M0/M1 核心命令仅依赖 Python 标准库；Stage 6/7 的 V06/V09 需要 `openpyxl` 与可选 `formulas`。`scripts/requirements.txt` 列出 M2 起全部依赖，**须安装在 Skill 包之外的独立虚拟环境中**，避免 `package_skill.py` 把 site-packages 打进分发 zip。缺失时按需安装，不得无条件重装。公式重算采用 LibreOffice → `formulas` → 内置求值器 → ERROR 四级降级；三者皆失效时禁止交付公式版清册。

Windows 约定：全程 `pathlib` 绝对路径、UTF-8 读写、控制台 UTF-8 重配置；zip 中文名按 `cp437 → gbk` 还原，失败保留原名并记 WARN；表格勾选符号 `ü`（Wingdings）显式映射。

## 九阶段执行流程

### Stage 0 — 初始化与配置校验
命令 `init`。复制 `assets/config_template.json` 到 run 目录，替换全部 `__REQUIRED__`，再执行。
输入：`org_config.json`；输出：`run_dir/`、`config_check.json`。
闸门：schema 校验、占位符扫描、语义校验（报告年合理、`base_year <= reporting_year`、合并方法枚举、实体 id 唯一、S3 类别在 1..15、报告模式与语言枚举、模式 B 强制保证等级/实质性/核查员、支出法必须有汇率表引用）。任一失败立即中止并列出全部缺失项。

### Stage 1 — 凭证抽取（M4 已实现）
命令 `extract --input-dir <凭证目录> [--hint <json>]`；默认读 `<run>/vouchers/`。四类加载器（均实现 `BaseExtractor`）：
- `pdf_invoice`：pypdf 提取文字，优先用**备注里的年月/计费周期**而非开票日期定期间；无文本层标待录。
- `excel_ledger`：openpyxl / xlrd 识别「月度列+合计」与「逐行发票台账」两种形态；从行标签（如「数量/50公斤」）提取单位；合计公式为空标 `broken_formula`；Wingdings `ü` 勾选只记提示不产生数值。
- `zip_bundle`：cp437→gbk 还原中文成员名，临时目录解包后递归分派，不留磁盘残留。
- `image_voucher`：**不做 OCR**，只登记待人工录入项；Agent 可通过 `hint.vision_candidates` 注入视觉候选值，仍标低置信度且必须签核。

规则（字段别名、期间正则、单位提示、脏数据原因文案）位于 `assets/extraction_rules.json`，运行时可用 `--hint` 覆盖；分类字段（`source_key` / `scope` / `entity_ref` 等）由 hint 或人工补录。
输出 `pending_ledger.json`：每行保留原始值、归一化值、期间轨迹、置信度、`needs_manual`、`warnings` 与**空的** `confirmation`。**只有金额没有物理量时绝不擅自折算**（油价/汇率等换算系数必须由运行时提供或人工填写）。

### Stage 2 — 人工确认闸（M4 已实现）
命令 `confirm [--batch-signoff <json>]`。人工可直接编辑 `pending_ledger.json` 逐行签核，也可用批量签核文件（含 `signed_by` / `signed_at`）填充未签核行。
闸门（任一不满足即退出码 2，且不生成 `activity_ledger.json`）：逐行 `signed_by`/`signed_at` 非空；归一化值与单位、期间起止齐备；估算值与 `carry_over_from` 必须写理由；`config_hash` 与配置一致。输出 `confirm_check.json`（含 `unsigned[]` 缺签清单），通过后产出可直接进入 Stage 3 的 `activity_ledger.json`。

### Stage 3 — 排放源识别（M1 已实现）
命令 `classify`。映射 S1/S2/S3 与 ISO 14064-1 大类、GHG Protocol 范围三 15 类；输出 15 类全覆盖表、逐行适用性与 `unmapped`。
闸门：重复执行签核校验与 `config_hash` 一致性；实体、气体、S2 口径、期间、S3 类别启用状态全部核对；未映射源进入 `unmapped` 待人工；判「不涉及」必须带理由。

### Stage 4 — 方法选择与因子匹配（M1 已实现）
命令 `match`。按 `methodology.per_source` → `default` 选择方法，按活动、方法、地区、年份、GWP 版本、有效期、优先级筛选因子；重放 `conversion_chain` 校验 `raw → normalized` 一致。
闸门：并列最高优先级的多因子 → `ambiguous` 并上报候选集；无方法/无因子/无对应气体 GWP → 不擅自取值；`scale` 必须由量纲契约 `scale_matches()` 复核，失配标 `dimension_mismatch`；`spend_based` 缺 `currency_conversion` 记 WARN。

### Stage 5 — 计算引擎（M1 已实现）
命令 `compute`。Decimal 纯函数、可重放、逐行血缘；统一 `tco2e = ad * ef * gwp / scale`；按类别与范围汇总，S2 双口径并列（总量只取 location-based），每行 `share` 以本次总量为分母。
闸门：输入必须是已签核台账；量纲不符、因子缺失、状态非 matched 时该行 `tco2e = null` 并记 WARN，禁止静默填 0。`results.json` 支持 `--append` 多版本，仅一个 `status = final`；旧 final 自动转 `superseded`。

### Stage 6 — 清册构建（M2 已实现）
命令 `inventory`。按 `assets/inventory_template.json` **新建**工作簿（不复制历史清册），生成 `boundary`、`source_identification`、`activity_data`、`factors`、`s12_calc`、按类别重复的 `S3_C1…`、`data_quality`、`quality_gaps`、`summary`。
闸门：排放与总量单元格全为公式且只引用其它单元格（禁止公式内写数值或常量分母）；占比分母恒引用 `summary!$B$5`；合计由显式 `SUM` 得到；清除 `wb._external_links`；写 AIGC 标识；同步产出 `formula_cache.json` 记录每个公式单元格的确定性期望值。数据质量评分表未配置时写 `N/A` 并登记缺口，绝不硬编码分数。

### Stage 7 — 勾稽校验（V01–V20 已实现）
命令 `check`，在 pipeline 中位于 Stage 8 之后、Stage 9 之前，以便同时校验清册、报告与交付完整性。
- M1：V01–V05、V08、V10、V11、V14、V15、V16、V17、V19。
- M2：**V06**（清册总量/逐行 == `results.json`，并扩展至报告摘要）、**V09**（零 `#REF!`、零外链、公式数一致、全量重算对账）。V09 重算四级降级：LibreOffice → `formulas` → 内置求值器 → ERROR，结果与 `formula_cache.json` 逐格比对（容差 1e-9）。
- M3：**V07**（CN/EN 所有字段与图表数值一致）、**V12**（模式 B 签核护栏，复核 manifest 与 docx 正文）、**V13**（未解析占位符与模板变量为零）。
- M5：**V20**（交付完整性：九个必需产物存在且非空、manifest 中每份报告存在、本轮无 ERROR 级发现）。仅在清册、报告与 run 目录齐备时执行，否则回到 deferred。

完整交付时 `rules_deferred` 为**空**；若清册或报告缺失，对应规则自动回到 deferred，不静默跳过。
闸门：**任何 ERROR 阻断交付**；输出 `checks.json`，并把精简结论回写 `results.checks`。

### Stage 8 — 报告生成（M3 已实现）
命令 `report`。`assets/report_layout.json` 定义章节与表格骨架，`assets/phrases.json` 提供中英一一对应的固定话术，`chart_gen.py` 用 `results.json` 生成范围与类别两张图，python-docx 按配置 `report.modes` × `report.languages` 生成最多四份文档。
硬约束：**动态数值只进表格单元格**，散文只用话术；CN/EN 共用同一 `final_version_id`；图表数据同源，中英标注成对。
**模式 B 护栏**：仅当 `org_config.report.signoff_ref` 指向的 `verification_signoff.json` 通过 schema 校验且含非空 `statement` 时才渲染声明段并输出正式文档；否则输出 `*_draft.docx`，声明段为占位符并附草稿提示。任何路径都不生成、不推断、不补写保证结论。V12 会复核 manifest 与 docx 正文。

### Stage 9 — 交付与打包（M5 已实现）
命令 `deliver [--out <zip 路径>]`，也是 `pipeline` 的最后一步。
闸门：先读 `checks.json`，**只有 `status=pass` 且无 ERROR 才允许交付**；否则返回 `blocked` 且不生成任何交付文件。
产物：`evidence_index.json`（凭证 → 台账行反向索引）、`delivery_manifest.json`（每个文件的角色、字节数、SHA-256、必需/可选标记、`final_version_id`、总量、AIGC 声明、校验规则与 deferred 列表）、以及 `delivery/<run_id>_delivery.zip`（含全部必需产物、报告 docx、图表 PNG、manifest 与证据索引）。缺任一必需文件时返回 `incomplete` 并列出 `missing[]`。

### 分发 Skill 本体

`scripts/cli.py` 是运行时入口；用官方 `package_skill.py <Skill 目录>` 打包 Skill 本身（与运行产物的交付 zip 是两回事）。依赖声明在 `scripts/requirements.txt`，须装在 **Skill 包之外**的独立虚拟环境，避免 site-packages 被打进分发包。

## 数据契约速览

| 文件 | 结构 | 关键约束 |
|---|---|---|
| `org_config.json` | 组织、报告年、合并方法、实体、气体、GWP 版本、S2 双口径、S3 类别与 cut-off、方法学、保证等级、报告模式与语言、货币汇率、重算政策 | 全部运行时注入；无占位符；模式 B 需保证信息 |
| `activity_ledger.json` | `rows[]`，每行含 raw / normalized / conversion_chain / data_quality / evidence_files / confirmation | 计算核心唯一输入；逐行签核 |
| `factor_library.json` | `factors[]`，每项含 value / unit / applicability / source / gwp_version / quality / scale | 强制来源与版本；无内置数值 |
| `results.json` | `versions[]`，含 lines / by_category / by_scope / total / checks | 唯一 final；报告只引用 final |

字段字典与校验规则见 `references/schemas.md` 与 `references/validation_rules.md`。

## 错误处理

| 情况 | 处理 |
|---|---|
| 配置含 `__REQUIRED__` / `TODO` / 占位年份 0 | Stage 0 中止，列出全部字段路径 |
| 台账存在未签核行 | 拒绝计算，导出缺签清单 |
| 一源多因子、方法或单位歧义 | 产出候选集，等待人工裁决 |
| 因子缺失或量纲不符 | 该行结果置 null 并记 WARN，禁止填 0 |
| PDF 无文本层 / 图片凭证 | 标记待录或由 Agent 视觉录候选值，仍须签核 |
| 公式重算报 `#REF!` 或存在外链 | Stage 7 ERROR，禁止交付 |
| 合计取数出现启发式 | 直接判 ERROR（见 `references/validation_rules.md`） |
| 模式 B 无授权签核 | 仅出草稿，结论段占位 |
| 命令属未实现里程碑 | 返回 `NOT_IMPLEMENTED` 与里程碑编号，不生成半成品 |
| 中英报告数值不一致 | Stage 7 ERROR，阻断交付 |
