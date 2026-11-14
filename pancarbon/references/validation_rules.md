# 勾稽校验规则（Stage 7）

规则由 `recalc_check.py` 实现（M1 起，M2/M3 补齐）。每条输出 `rule_id`、`severity`（`ERROR` / `WARN`）、`object`、`observed`、`expected`。**任何 ERROR 阻断交付**；WARN 必须写入交付清单。

## 规则清单

| ID | 严重度 | 检测对象 | 判定 |
|---|---|---|---|
| V01 | ERROR | 逐行公式 | `tco2e == ad * ef * gwp / scale`；`scale` 必须来自因子库，不得为代码常量 |
| V02 | ERROR | 量纲 | `normalized.unit` 与因子 `unit` 分母可约；量级差异超过单位契约允许范围时报错 |
| V03 | ERROR | 分项与合计 | 明细求和 == 分组小计 == 范围小计；禁止「共计」沿用历史值 |
| V04 | ERROR | 总量 | `S1 + S2[location_based] + sum(S3) == total` |
| V05 | ERROR | 占比 | 所有占比列分母 == 本次报告总量；禁止引用旧模板常量或固定数值 |
| V06 | ERROR | 跨产物一致 | 清册合计 == `results.json` final 总量 == 报告摘要/概况/结论表数值 |
| V07 | ERROR | 中英一致 | CN/EN 同键指标数值逐项相等（含图表数据） |
| V08 | ERROR | 版本 | `versions[]` 恰有一个 `status = final`；`final_version_id` 存在且被所有报告引用 |
| V09 | ERROR | 公式重算 | xlsx 重算零公式错误、零 `#REF!`、零外链；重算值与纯函数结果双轨对账一致 |
| V10 | ERROR | 因子与单位一致性 | 因子版本/有效期/GWP 版本/适用地区与配置一致；一行内单位与期间口径唯一 |
| V11 | ERROR | 确认闸 | 所有参与计算的台账行 `signed_by` / `signed_at` 非空；估算与沿用值有理由 |
| V12 | ERROR | 模式 B 护栏 | 无签核时声明段必须为占位符，且文件名带 `_draft` |
| V13 | ERROR | 占位符 | 报告中不存在未解析占位符或空白数值单元格 |
| V14 | ERROR | 启发式禁令 | 代码中不得出现「取合计行最大值」「取某列最大值」「沿用上一版本数值」等模式；静态扫描 + 运行期断言 |
| V15 | WARN | S2 双口径 | 两口径均存在且差异已说明；`market_instruments` 与 market_based 结果配套 |
| V16 | WARN | 异常波动 | 相对基准年变化超过 `quality.volatility_warn_pct` 时提示复核 |
| V17 | WARN | 数据质量 | 抽样比例/样本量低于配置要求、估算占比过高、`carry_over_from` 未更新 |
| V18 | WARN | 缺口 | 「数据质量与缺口说明」中未量化类别或沿用值需人工复核 |
| V19 | ERROR | 期间 | 所有行落在报告年内，或按配置规则显式拆分；`basis` 与 `billing_note` 一致 |
| V20 | ERROR | 交付完整性 | 清册、中英报告、`results.json`、`checks.json`、证据索引、`config_check.json` 齐全 |

## 已知事故类型 → 规则映射（抽象描述，不含任何具体数值）

| 事故类型 | 拦截规则 |
|---|---|
| 「共计」单元格沿用上年值，与明细和不等 | V03、V06 |
| 占比列分母使用历史模板常量 | V05 |
| 同一类别存在多张草稿表并被同时汇总 | V08、V14 |
| 自动抽数脚本用「合计行取行内最大数值」导致总量虚高 | V14、V06、V03 |
| 中英报告同一指标数值不同 | V07 |
| 分项和与类别总计不符 | V03、V06 |
| 分母多除或少除一次量级 | V01、V02 |
| 外链损坏产生 `#REF!` | V09 |
| 方法学变更后仍与历史年份直接比较 | V16、V17 |
| 未量化类别被记作 0 而缺少说明 | V18 |

## 重算三级降级

1. LibreOffice headless 重算并回填缓存值；
2. `formulas` 库重算并与纯函数结果对账；
3. 两者皆不可用 → ERROR，禁止交付公式版清册；可另出纯值版 + 公式文本备份作为降级交付（M2 实现）。

## checks.json 输出

`status`（`pass` / `fail`）、`errors[]`、`warnings[]`，每项含 `rule`、`object`、`observed`、`expected`、`message`。`fail` 时 `deliver` 命令必须拒绝生成交付包。

## M1 / M2 / M3 实现状态

- **M1 已实现**：V01、V02、V03、V04、V05、V08、V10、V11、V14、V15、V16、V17、V19。
- **M2 已实现**：V06、V09。
- **M3 已实现**：V07、V12、V13；V06 扩展至报告摘要数值。
- **M5 已实现**：V20（九个必需产物存在且非空、manifest 中每份报告存在、本轮无 ERROR 级发现）。`checks.json` 自身不在检查清单内，因为它正由本轮生成。
- **完整交付时 `rules_deferred` 为空**。未生成清册时 V06/V09、未生成报告时 V07/V12/V13、交付条件不齐时 V20 自动回到 deferred，避免静默跳过。
- **三轨对账**：`compute.py` 的 `Decimal` 路径 → V01 的独立 `Fraction` 复算 → V09 的 xlsx 公式重算。三者一致才通过。
- V06 同时校验 `summary` 五个总量单元格与 `s12_calc`/`S3_C*` 每一条排放行，防止清册与 `results.json` 脱节。
- V09 静态检查 `#REF!`、外链标记、`xl/externalLinks/`、`wb._external_links`、公式单元格数量；动态检查采用 LibreOffice headless → `formulas` → 内置轻量求值器 → ERROR 四级降级，重算结果与 `formula_cache.json` 逐格比对（容差 1e-9）。
- V14 静态扫描 `scripts/*.py`，检测 `max()` 与合计类关键词同行的启发式取数；规则引擎自身文件排除扫描以免自命中。
- V05 校验每行 `share` 的分母为**当前版本** `total`，专治比例列沿用历史模板常量；清册里的占比分母统一引用 `summary!$B$5`。
- V08 要求 `versions[]` 恰有一个 `final` 且 `final_version_id` 指向它，专治同一清册内多套口径并存。
- V07 按报告模式配对 zh/en 两份文档的 `fields` 键集合与数值、以及 `chart_data`，任一不等即 ERROR，专治历史中英报告同一指标数值矛盾。
- V12 复核模式 B：无签核必须 `draft=True` / 文件名带 `_draft` / `statement_is_placeholder=True` / 正文含占位符；有签核反之且正文不得残留占位符。
- V13 复核 `unresolved_placeholders`、`template_tokens_found` 为零，并实际扫描交付 docx 正文中的 `{{`。
