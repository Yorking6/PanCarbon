# 报告字段映射（抽象）

模板位于 `assets/`：`report_A_cn.docx` / `report_A_en.docx` / `report_B_cn.docx` / `report_B_en.docx`（M3 生成骨架）。固定话术位于 `assets/phrases.json`。**所有动态数值只填表格单元格占位符**，散文不得含数字。

## 1. 通用规则

- CN 与 EN 的 `phrases.json` 键一一对应；Stage 7 按键配对，逐项比对两版表格中的数值。
- 报告只引用 `results.json` 的 `final_version_id`；引用其它版本判 ERROR。
- 图表数据只取 `results.json`；图题、轴标签从 `phrases.json` 取，保证中英标注一致。
- 封面标题、标准名称、日期、机构名由 `org_config.report.titles` 与签署信息注入，不进话术库。
- 签署表、结尾标记、审核员等来自配置或签核文件，禁止推测默认值。

## 2. 模式 A（组织排放/计算报告）7 章

| 章节 | 表格 | 动态字段来源 |
|---|---|---|
| 封面 | — | `report.titles`、标准名称（配置）、日期、机构 |
| 基本信息 | 审核员/现场日期/公司信息/联系人/行业 | `org_config` + 签核信息 |
| 概况 | 基准年、标准、计算范围、报告边界、计算结论、总量 | `org_config` + `results.total` |
| 温室气体排放计算摘要 | 各排放源 Tons / 比例 / 小计 / 总计 | `results.by_scope` / `by_category`；比例分母取本次总量 |
| 4.1 排放源的统计和测量 | 范围 × 类别 × 设施 × 测量方法 × 气体类型 | `classification.json` |
| 4.2 活动水平数据及来源 | 逐源活动数据、单位、计算方法、凭证 | `activity_ledger.raw/normalized/provenance` |
| 4.3 排放结构与计算结果 | 逐源 AD × EF×GWP → tCO2e | `results.lines` |
| 4.4 排放因子来源 | 因子、单位、来源；区域因子；GWP 表 | `factor_library` |
| 数据质量管理 | 三条固定核查话术 | `phrases.json`（无动态值） |
| 不确定性分析 | 评分表、等级表、按占比加权评分表 | `activity_ledger.data_quality` + `org_config.quality` |
| 证明文件清单 | 序号 / 凭证文档名 | `evidence_files[]` 去重汇总 |
| 签署 | 审核员、审核组长、审批人、日期 | 签核文件 |
| 结尾 | 固定结束标记 | `phrases.json` |

计算结论为固定句式（由 `phrases.json` 提供），**不得由模型自行撰写符合性判断**；若需调整措辞，由使用者提供文本并经签核。

## 3. 模式 B（第三方核查，ISO 14064-3）

| 章节 | 来源类别 | 字段 |
|---|---|---|
| 核查目的、范围与边界 | 清册 | 组织、报告年、边界、被核查数据范围、总量明细 |
| 准则 | 配置 | 依据标准名称与版本、组织制度 |
| 保证等级与实质性 | **人工输入** | 等级、实质性阈值、确定依据 |
| 核查程序 | **人工输入** + 清册 | 抽样计划、访谈记录、交叉核对、重新计算结果（来自 `results.json` / `checks.json`） |
| 发现与观察项 | 清册 + 人工 | 数据质量缺口、方法变更、不符合项与整改要求 |
| 核查声明 | **人工输入，禁止自动生成** | 意见类型、结论、核查员/机构、签署日期 |
| 附录 | 清册 | 证明文件清单、被核查清册索引 |

### 合规护栏

- 命令 `report --mode B` 默认只生成 `*_draft.docx`；声明章节写入 `phrases.json` 的 `report.B.statement_placeholder`。
- 仅当 `org_config.report.signoff_ref` 指向的 `verification_signoff.json` 含 `signed_by`、`signed_at`、`assurance_level`，且通过确认闸语义校验，才渲染声明段。
- 缺失或未签核时：草稿、占位符、退出码 0 但报告文件名带 `_draft` 后缀，并在 `checks.json` 记 WARN。
- 任何情况下不得由模型推断、补写或润色保证结论。

## 4. 占位符约定

- 表格单元格占位符形如 `{{results.by_scope.S1}}`、`{{config.reporting_year}}`（尖括号仅用于文档内部说明，运行时代理解析）。
- 数值格式化（小数位、千分位、单位）由渲染层统一处理，模板不预置格式。
- 未解析到值的占位符 → Stage 7 ERROR，禁止输出空白或占位文本。
- 中英两版使用同一占位符键，确保数值唯一来源。

## 5. 交付命名

`<run_id>_<mode>_<lang>.docx`（模式 B 未签核追加 `_draft`）。每份报告附对应语言的图表（若 `report.charts = true`）。
