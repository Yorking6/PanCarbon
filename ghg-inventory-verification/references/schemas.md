# 数据契约字段字典

四份 JSON Schema 位于 `assets/schemas/`。`validate_config.py` 内置纯标准库校验器，实现 `type`（含类型数组）、`required`、`properties`、`items`、`enum`、`minItems`、`minLength`、`minimum`、`maximum`；未识别关键字（如 `$schema`、`title`、`description`）忽略。若运行环境装有 `jsonschema`，可切换为标准校验，两者结论须一致。

## 通用约定

- 所有文件 UTF-8、无 BOM、LF 换行。
- 模板中 `__REQUIRED__`、`TODO`、`PLACEHOLDER` 为占位符；Stage 0 扫描到任一即中止。
- `config_hash` = 规范化后 `org_config.json` 的 SHA-256；台账与结果均携带该值，用于防止配置与结果错配。
- 金额、数量一律用 JSON number，禁止科学计数字符串；缺失值用 `null`，禁止用 0 表示缺失。
- 日期时间用 ISO 8601 字符串。

## 1. org_config.json

| 字段 | 类型 | 约束 |
|---|---|---|
| `schema_version` | string | 非空 |
| `organization.name` / `boundary_description` | string | 非空，运行时注入 |
| `organization.addresses[]` | string[] | 可空 |
| `reporting_year` | integer | 1900..2100，且不得为占位 0 |
| `base_year` | integer 或 null | 小于等于 `reporting_year` |
| `consolidation_method` | enum | `operational_control` / `financial_control` / `equity_share` |
| `entities[]` | object[] | 至少 1 项，`id` 唯一且非空 |
| `entities[].grid_region_ref` | string 或 null | 指向因子库地区键 |
| `gases[]` | string[] | 至少 1 项 |
| `gwp_version` | enum | `AR4` / `AR5` / `AR6` |
| `scope2.modes[]` | enum[] | `location_based` / `market_based`，至少 1 项 |
| `scope2.market_instruments[]` | object[] | market_based 时不得为空 |
| `scope3.enabled_categories[]` | int[] | 1..15 |
| `scope3.not_applicable_reasons` | object | 未启用类别必须有理由 |
| `scope3.cutoff` | object | `rule` 可空，`threshold_pct` ≥ 0 |
| `methodology.default` / `per_source` | string/object | 方法键见 methodology.md |
| `assurance.level` / `materiality` / `verifier` | 可空 | 模式 B 时三项必填 |
| `report.modes[]` | enum[] | `A` / `B` |
| `report.languages[]` | enum[] | `zh` / `en` |
| `report.charts` | boolean | 是否内嵌图表 |
| `report.signoff_ref` | string 或 null | 模式 B 签核文件路径 |
| `currency.code` | string | 长度 ≥ 3 |
| `currency.fx_table_ref` | string 或 null | 使用支出法或跨币种因子时必填 |
| `quality` | object | 分数表、等级阈值、波动告警阈值 |
| `factor_library_ref` / `activity_ledger_ref` | string | 非空，运行时文件路径 |

## 2. activity_ledger.json

顶层：`schema_version`、`config_hash`、`rows[]`（至少 1 行）。

每行必填：`row_id`、`entity_ref`、`period`、`scope`、`raw`、`normalized`、`conversion_chain`、`data_quality`、`estimated`、`evidence_files`、`confirmation`。

| 字段 | 说明 |
|---|---|
| `row_id` | 全表唯一，贯穿 matched / results / 清册 / 报告 |
| `entity_ref` | 必须存在于 `org_config.entities[].id` |
| `period.start/end/basis` | basis ∈ `consumption` / `billing` / `estimated` |
| `scope` | `S1` / `S2` / `S3` |
| `s3_category` | 1..15，仅 S3 必填 |
| `raw.value/unit/source_file/extractor` | 原始值、原始单位、凭证路径、抽取器标识 |
| `raw.confidence` | 图片/视觉录入候选值时标 `low` |
| `normalized.value/unit` | 归一化后的活动数据，unit 必须能与因子分母相约 |
| `conversion_chain[]` | 每步 `op/from_unit/to_unit/factor/reference/note` |
| `data_quality` | `activity` X/Y/Z、`factor` A..F、`instrument` L/M/S |
| `estimated` / `estimation_note` | 估算必须为 true 且写明理由 |
| `carry_over_from` | 沿用既有结果时填写来源标识 |
| `evidence_files[]` | 凭证路径列表 |
| `confirmation.signed_by/signed_at` | **非空；Stage 2 硬闸门** |

## 3. factor_library.json

顶层：`schema_version`、`factors[]`（至少 1 项）。模板 `_example_structure` 只是结构说明，不参与校验。

每项必填：`id`、`value`、`unit`、`applicability`、`source`、`gwp_version`、`quality`、`scale`。

| 字段 | 说明 |
|---|---|
| `value` / `unit` | 因子数值与单位，运行时注入，包内不含任何真实值 |
| `gases` | 分气体系数，合成 CO2e 因子时留空或标记 |
| `applicability.activity/region/year/method` | 决定匹配优先级 |
| `source.name/version/url/retrieved_at` | 强制来源与版本，禁止无来源因子 |
| `gwp_version` | 与配置一致；不适用填 `not_applicable` |
| `valid_from` / `valid_to` | 有效期，报告年须落在有效期内 |
| `priority` | 多候选时按优先级排序，但仍须人工裁决 |
| `scale` | 显式量纲除数，禁止代码硬编码分母 |

## 4. results.json

顶层：`run_id`、`config_hash`、`final_version_id`、`versions[]`、`checks`。

`versions[]` 每项：`version_id`、`method`、`status`（`draft`/`final`/`superseded`）、`lines[]`、`by_category`、`by_scope`、`total`。

`lines[]` 每项：`row_id`、`factor_id`、`method`、`formula`、`ad`、`ef`、`gwp`、`scale`、`tco2e`、`warnings[]`、`provenance`。

`provenance` 必填 `config_hash`、`ledger_row`、`factor_id`，并携带 `gwp_version` 与 `conversion_chain` 快照。

`by_scope.S1` 为数值；`S2` 为对象（双口径各一键）；`S3` 为对象（按 S3-1..S3-15）。`total` 必须等于 `S1 + S2[location_based] + S3` 各类之和。

`checks`：`status`（`pending`/`pass`/`fail`）、`errors[]`、`warnings[]`。

## 5. 校验顺序（Stage 0）

1. JSON 可解析、文件存在、UTF-8。
2. 占位符全局扫描（`__REQUIRED__` / `TODO` / `PLACEHOLDER`）。
3. Schema 结构校验，收集全部错误而非遇错即停。
4. 语义校验（见 SKILL.md Stage 0 闸门）。
5. 通过则创建 run 目录骨架并写 `config_check.json`；失败则退出码 2，不创建任何阶段产物。

## 6. M1 中间产物契约

`activity_ledger` 新增两个可选字段：`gas`（因子库 `gases` 表的键，默认 `CO2`）与 `scope2_mode`（`location_based` / `market_based`，S2 行默认前者）。`results.lines[]` 新增 `share`（以该版本 `total` 为分母，V05 校验）。

`classification.json`（Stage 3 输出）：`stage`、`status`、`config_hash`、`rows[]`、`categories`、`unmapped[]`、`errors[]`、`warnings[]`。`rows[]` 每项含 `row_id`、`entity_ref`、`scope`、`iso_category`、`s3_category`、`source_key`、`gas`、`scope2_mode`、`applicable`、`reason_if_not`。`categories` 必含 `S1`、`S2` 与 `S3-1` 至 `S3-15` 全部键，禁用类别须带理由。

`matched.json`（Stage 4 输出）：`stage`、`status`（`pass` / `partial` / `fail`）、`config_hash`、`lines[]`、`candidates[]`、`errors[]`、`warnings[]`。`lines[]` 每项含 `row_id`、`method`、`method_origin`、`factor_id`、`ad`、`ad_unit`、`ef`、`ef_unit`、`gwp`、`scale`、`derived_scale`、`status`（`matched` / `ambiguous` / `missing` / `dimension_mismatch` / `conversion_mismatch`）、`candidates[]`、`warnings[]`、`applied_conversion[]`。只有 `status = matched` 的行会产生排放量。

`checks.json`（Stage 7 输出）：`stage`、`status`、`config_hash`、`rules_run[]`、`rules_deferred`（映射到目标里程碑）、`errors[]`、`warnings[]`、`dual_track`（`status` / `lines_checked` / `max_delta`）、`v14`（`files_scanned` / `hits` / `status`）。错误项含 `rule`、`object`、`observed`、`expected`、`message`。

`config_hash` 贯穿四个产物；任一不一致即判 ERROR，防止配置、台账与结果错配。

## 7. M2 产物契约

`formula_cache.json`（Stage 6 输出）：`workbook`、`formula_pattern`、`config_hash`、`final_version_id`、`sheets[]`、`formula_cell_count`、`formula_cells[]`、`cells`（`SHEET!CELL` → 期望数值）、`key_cells`（`total` / `S1` / `S2_location_based` / `S3` / `S2_market_based` / 三个小计）、`quality_gaps`、`aigc_note`。V06 用 `key_cells` 与 `cells` 比对 `results.json`，V09 用 `cells` 比对公式重算结果。

`checks.json` 在 M2 增加 `v09` 对象：`engine`（`libreoffice` / `formulas` / `builtin`）、`formula_cells`、`cells_checked`、`max_delta`、`external_links`、`issues[]`；`milestone` 变为 `M1+M2`，`rules_run` 追加 `V06`、`V09`，`rules_deferred` 只余 M3/M5 的四条。

`ghg_inventory.xlsx` 不是 JSON，但受三条结构约束：公式单元格数量等于 `formula_cell_count`；不存在 `xl/externalLinks/`；`wb._external_links` 为空。

## 8. M3 产物契约

`verification_signoff.json`（人工提供，可选）：`signed_by`、`signed_at`、`assurance_level`（`limited` / `reasonable`）、`materiality`、`verifier`、`statement`（必填且非空）、可选 `procedures[]` 与 `findings[]`。schema 位于 `assets/schemas/verification_signoff.schema.json`。任何校验失败都视为「无签核」，只出草稿。

`report_manifest.json`（Stage 8 输出）：`run_id`、`config_hash`、`final_version_id`、`signoff_valid`、`signoff_issues[]`、`phrases_paired`、`documents[]`。每个 document 含 `path`、`mode`、`language`、`draft`、`signoff`、`statement_rendered`、`statement_is_placeholder`、`fields`（所有渲染进表格的数值字段）、`chart_data`（`scope` / `category` / `total`）、`unresolved_placeholders`、`template_tokens_found`、`sections[]`、`chart_files[]`。

`fields` 的键是 V06/V07 的比对基准，命名稳定：`total`、`S1`、`S2_location`、`S2_market`、`S3`、`share.<key>`、`line.<row_id>.<ad|ef|gwp|scale|tco2e>`、`factor.<id>.value`、`chart.scope.<key>`、`chart.category.<key>`、`chart.total`、`reporting_year`、`base_year`、`evidence_count`、`finding_count`、`assurance.materiality`。

`assets/report_layout.json` 定义模式 A/B 的 sections（kind：`key_value` / `table` / `prose` / `guarded_statement` / `charts`）与 data source；`assets/phrases.json` 的 zh/en 键必须一一对应且非空。

## 9. M4 产物契约

`pending_ledger.json`（Stage 1 输出）：`schema_version`、`config_hash`、`rows[]`、`warnings[]`、`extractor_stats`。每行在 `activity_ledger` 行结构基础上增加 `needs_manual`、`warnings[]`，`period` 增加 `confidence` / `needs_manual` / `warnings`，`confirmation.signed_by` / `signed_at` 允许 `null`（此时禁止进入 Stage 3）。`normalized.value` 允许 `null` 表示未解析，`raw.value` 允许字符串保留原貌。

`confirm_check.json`（Stage 2 输出）：`stage`、`status`、`rows`、`unsigned[]`、`errors[]`、`warnings[]`、`batch_signoff`、`config_hash`。`unsigned[]` 即缺签清单；`status=fail` 时 `activity_ledger.json` 不得生成或覆盖。

`assets/extraction_rules.json`：`field_aliases`（中英字段名，通用词汇，不含任何组织名）、`period_patterns`（`yyyymm` / `date_range` / `date` / `yyyymm_slash`）、`unit_hints`、`month_columns`、`checkbox_symbols`、`unit_in_label_patterns`、`manual_reasons`。不含价格、汇率、排放因子或任何真实数值常量。

运行时 `hint`（`--hint` 或凭证目录下的 `extraction_hint.json`）可提供：`source_key`、`scope`、`s3_category`、`entity_ref`、`scope2_mode`、`gas`、`vision_candidates`（文件名 → `value` / `unit` / `period`）。分类字段缺失时需在人工确认阶段补录。

## 10. M5 产物契约

`evidence_index.json`（Stage 9 输出）：`schema_version`、`row_count`、`evidence_count`、`evidence[]`（`file` → 引用该凭证的 `rows[]`）。由已签核台账反向汇总，用于核查证据链。

`delivery_manifest.json`（Stage 9 输出）：`schema_version`、`status`、`generated_at`（UTC ISO）、`run_id`、`config_hash`、`final_version_id`、`checks_status`、`rules_run[]`、`rules_deferred`、`total_tco2e`、`evidence_count`、`aigc_note`、`items[]`、`warnings[]`、`bundle`。

`items[]` 每项：`path`、`role`、`required`、`present`、`bytes`、`sha256`。必需角色见 `package_delivery.REQUIRED_FILES`（10 项：配置、因子库、已签核台账、分类、匹配、结果、清册、公式缓存、报告 manifest、校验报告），可选角色见 `OPTIONAL_FILES`（Stage 0/1/2 检查、模式 B 签核、hint、批量签核）。报告 docx 与图表 PNG 从 `report_manifest.json` 动态加入，均标为必需。

`delivery/<run_id>_delivery.zip` 含全部 items、`delivery_manifest.json` 与 `evidence_index.json`。**注意区分**：这是运行产物的交付包；`package_skill.py` 打的是 Skill 本体分发包，两者不同。
