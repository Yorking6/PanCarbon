# 清册版式与公式模式（抽象）

清册结构定义于 `assets/inventory_template.json`，由 Stage 6 的 `build_inventory.py` 解析。**任何具体表头坐标、企业名、数值、年份都不得写进代码**：表头文字从 `assets/phrases.json` 的 `sheet.*` 键取，行列由锚点推导。

## 1. Sheet 清单（key 稳定，标题可本地化）

| key | 作用 | kind |
|---|---|---|
| `boundary` | 组织与报告边界、合并方法、报告年、实体清单 | metadata |
| `source_identification` | 范围 × ISO 类别 × S3 类别 × 气体种类识别矩阵 | matrix |
| `activity_data` | 活动数据汇总，按实体分列 + 合计 + 单位 | table |
| `factors` | 排放因子库快照（含来源、版本、GWP 版本、scale、质量等级） | table |
| `s12_calc` | 范围一/二计算，分组小计与占比 | formula |
| `s3_category` | 按 S3 类别重复生成的计算表 | formula_repeating |
| `data_quality` | 数据质量分级与加权评分 | table |
| `quality_gaps` | 数据缺口、处理方式、方法变更、总量汇总 | table |
| `summary` | S1/S2/S3 与总量汇总 | formula |

「数据质量与缺口说明」为独立 sheet，记录三类内容：缺口（编号、类别、数据项、描述、处理方式、影响估算）、方法或口径变更说明、范围与总量汇总。沿用既有结果、未量化类别、抽样比例不足等都必须在此登记。

## 2. 锚点机制

- 每个 sheet 以 `anchor` 定义表头起始行列；数据区从锚点向下推导，禁止硬编码固定行号。
- 列以字段名（field key）寻址而非字母；写公式时由解析器把字段名解析为列字母。
- 合计行用显式 `subtotal` / `total` 字段标记，值由公式 `SUM(明细区)` 得到；**禁止用「扫描含合计字样的行并取最大值」之类启发式定位合计**。
- 同一工作簿内不得出现两个语义相同的合计表；历史草稿表若保留，必须标 `superseded` 且不参与汇总。

## 3. 公式模式

统一模式：

```
tco2e = ad * ef * gwp / scale
```

`scale` 来自 `factor_library.factors[].scale`。写入 Excel 时：

- 活动数据、因子、GWP、scale 均引用单元格，不在公式里写数值常量；
- 逸散类：`ad × 逸散率 × GWP / scale`；
- 支出法：`金额 × 万元倍数 × EF / 汇率 / scale`，其中万元倍数、汇率引用 `factors` sheet 的具名单元格；
- 距离法：`吨公里 × EF / scale`；
- 占比：`= 本行排放量 / 本次报告总量`（分母必须引用 `summary` 的总量单元格，禁止引用旧值或固定数）；
- 分组小计：`= SUM(该组明细)`；
- 总计：`= S1小计 + S2小计 + S3各类小计`。

**已知事故类型（必须由 Stage 7 拦截）**：分母多除或少除一次量级；占比分母沿用历史模板值；小计与明细和不一致；同一类别多个草稿表并存且被同时汇总；外链损坏导致 `#REF!`。

## 4. 写入规则

- 公式以字符串写入，不写死值；保留 `SUM` 等可重算公式。
- 生成后清空 `wb._external_links`，并在 Stage 7 复检零外链。
- 写 `wb.properties`：标题、创建者标识、AI 生成内容标识；具体文字由 `phrases.json` 与配置注入。
- 不复制既有工作簿作为模板（避免把历史数据与残留年份带进来）；从 `inventory_template.json` 新建。
- 样式常量（表头填充、合计填充、备注填充、数字格式）从模板 `styles` 读取。

## 5. 与 results.json 的关系

清册是 `results.json` 中 `final` 版本的**公式化呈现**。二者必须双向一致：

- 清册每个明细行的 `row_id` 对应 `lines[].row_id`；
- 清册 `factors` sheet 对应 `factor_library.json` 的快照；
- 清册 `summary` 的总量等于 `versions[final].total`；
- Stage 7 用 `formulas` 或 LibreOffice 重算清册，与纯函数结果双轨对账。

不一致时以 `results.json` 为唯一真值，回修清册，禁止反向改写结果。

## 6. M2 落地形态

`build_inventory.py` 按 `assets/inventory_template.json` 从零新建工作簿，sheet 名用 ASCII key（`boundary`、`source_identification`、`activity_data`、`factors`、`s12_calc`、`S3_C1`…`S3_C15`、`data_quality`、`quality_gaps`、`summary`），表头写在第 1 行，数据从第 2 行开始。合成用例生成 16 个 sheet、98 个公式单元格。

坐标约定：

| 表 | 关键列 |
|---|---|
| `activity_data` | H = 归一化活动数据，供计算表 E 列引用 |
| `factors` | B = 因子值，K = scale，M = 该行实际使用的 GWP |
| `s12_calc` / `S3_C*` | E = `=activity_data!H<n>`，G/H/I = 因子引用，J = `=E*G*H/I`，K = `=J/summary!$B$5` |
| `s12_calc` | 三个小计行：S1、S2 location、S2 market |
| `S3_C<n>` | 末行 `=SUM(J2:J<last>)` 为该类别小计 |
| `summary` | B2=S1、B3=S2 location、B4=各类别小计之和、B5=`=B2+B3+B4`、B6=S2 market；C 列占比分母恒为 `$B$5` |
| `quality_gaps` | 三段：缺口清单、方法变更、总量汇总（B 列引用 `summary`） |

`formula_cache.json` 记录 `formula_pattern`、`sheets`、`formula_cell_count`、`formula_cells`、`cells`（每个公式单元格的确定性期望值）、`key_cells`、`quality_gaps` 数量与 AIGC 标识。V06/V09 以它为对账基准。

数据质量评分表来自 `org_config.quality.scores`，未配置时 `data_quality` 写 `N/A` 并在 `quality_gaps` 登记一条缺口，绝不硬编码 X/Y/Z、A–F、L/M/S 的分值。
