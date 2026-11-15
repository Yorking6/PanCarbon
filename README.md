<div align="center">

# 盘碳 PanCarbon

**组织温室气体排放核算与核查 Agent Skill**

依据 GHG Protocol 与 ISO 14064-1/-3 · 原始凭证进 · 排放清册与报告出

![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![Standards](https://img.shields.io/badge/Standard-GHG%20Protocol%20%7C%20ISO%2014064-green.svg)
![Tests](https://img.shields.io/badge/Tests-102%20passing-brightgreen.svg)

[下载 Skill 包](https://github.com/Yorking6/PanCarbon/releases) · [使用方式总览](#三使用方式总览) · [常见问题](#七常见问题与报错排查)

</div>

---

**盘碳**（谐音「盘查」）把组织一年的碳排放，盘成一本经得起审计的账。你提供报告年内的电费、燃气、柴油、运输、采购、差旅等使用数据与凭证，它计算对应的二氧化碳当量排放（tCO2e），生成带公式的 Excel 排放清册、中英双语的排放报告或核查报告，并以 SHA-256 交付清单归档。

> **纯抽象通用框架**：包内不含任何真实企业数据、排放因子数值或报告模板文字。组织边界、报告年、实体清单、排放因子库、方法学与保证等级全部由运行时配置注入。

---

## 目录

| # | 章节 | # | 章节 |
|---|------|---|------|
| 一 | [项目简介](#一项目简介) | 六 | [产出文件说明](#六产出文件说明) |
| 二 | [核心特性](#二核心特性) | 七 | [常见问题与报错排查](#七常见问题与报错排查) |
| 三 | [使用方式总览](#三使用方式总览) | 八 | [安全与合规须知](#八安全与合规须知) |
| 四 | [在 AI Agent 中使用](#四在-ai-agent-中使用) | 九 | [技术架构](#九技术架构) |
| 五 | [本地命令行使用](#五本地命令行使用) | 十 | [参与贡献与许可](#十参与贡献与许可) |

---

## 一、项目简介

一次完整的组织碳盘查，通常要做三件事：**记账**（识别每个排放源用了多少能源与物料）、**出报表**（汇总成清册与报告）、**审计**（让第三方核得上账）。盘碳把这三件事放进同一条流水线：

```
 输入                          流水线自动完成                        输出
 ────────────────             ──────────────────────────           ──────────────────────
 电费发票      ─┐              ① 识别单据中的用量与报告期间
 燃气/柴油发票 ─┤              ② 人工确认并签核每一行数据             排放核查清册
 运输记录      ─┼──▶ 盘碳 ──▶  ③ 排放源分类与因子匹配      ──▶       （Excel，全公式）
 采购/差旅台账 ─┤              ④ 统一公式计算 tCO2e                  排放/核查报告
 照片与扫描件  ─┘              ⑤ 20 条勾稽规则校验                   （Word，中英可选）
                               ⑥ 打包交付并记录文件指纹               交付包与证据索引
```

它和普通计算器的区别，在于**专为「经得起第三方核查」设计**：

- 每一行数据必须有人签名确认，才允许进入计算，此闸不可绕过；
- 每一笔结果都能沿血缘倒查回最初的那张发票；
- 20 条勾稽规则自动检查算术、量纲、中英报告一致性，发现 ERROR 坚决阻断交付；
- 正式核查结论必须由具备资质的核查人员签署，工具在任何路径下都不代写。

## 二、核心特性

| 特性 | 说明 |
|---|---|
| 九阶段流水线 | 配置校验 → 凭证抽取 → 确认闸 → 分类 → 因子匹配 → 计算 → 清册 → 报告 → 校验 → 交付 |
| 可插拔凭证抽取 | PDF 发票、Excel 台账、zip 压缩包、图片凭证四类抽取器，字段别名与期间规则可配置 |
| 人工确认闸 | 每行活动数据必须签核后才进入计算；未签核行硬拒绝，不代签、不默认填空 |
| 统一计算公式 | `tco2e = ad × ef × gwp / scale`，量纲契约由因子库显式声明，杜绝量级错误 |
| 公式版清册 | 16 个工作表、全公式驱动，公式重算与 Decimal 纯函数双轨对账 |
| 中英双语报告 | 模式 A（ISO 14064-1 计算报告）/ 模式 B（ISO 14064-3 核查报告），中英数值逐项可对账 |
| 勾稽校验引擎 | V01–V20：数值勾稽、量纲、签核闸、启发式禁令、CN/EN 一致性、交付完整性 |
| 可追溯交付 | 每份交付文件带 SHA-256 指纹与 AIGC 声明，凭证到结果的反向索引 |

## 三、使用方式总览

盘碳支持三种使用方式，底层是**同一套计算引擎**，结果完全一致：

| 方式 | 适合人群 | 需要准备 | 参考章节 |
|---|---|---|---|
| **AI Agent 中使用** | 在 WorkBuddy、Claude Code、Codex 等智能体环境中工作 | 导入 Skill 包或配置指引文件 | [第四章](#四在-ai-agent-中使用) |
| **本地命令行** | 需要完全掌控流程、批量处理或集成为自动化的用户 | Python 3.10+ 与依赖安装 | [第五章](#五本地命令行使用) |
| **直接跑样例** | 想先看效果再决定 | 无 | [学习样例](#学习样例) |

> 无论哪种方式，**人工确认闸都会要求你对每一行数据签名确认**——这是本工具的合规底线。请逐条核对后再确认，不要批量代签。

## 四、在 AI Agent 中使用

在 AI Agent 中使用盘碳，核心只有两件事：**让 Agent 找得到 Skill**，以及**给 Agent 一个可用的 Python 环境**。以下按平台分别说明。

### 4.1 WorkBuddy

1. 在 [Releases 页面](https://github.com/Yorking6/PanCarbon/releases) 下载最新版 `pancarbon.zip`，无需解压；
2. 打开 WorkBuddy 的技能（Skill）管理界面，选择「安装本地 Skill / 从文件导入」，选中 `pancarbon.zip` 确认安装；
3. 把凭证材料放入一个文件夹，然后在对话中说：

   > 请用盘碳 Skill，帮我核算我司 2025 年度的温室气体排放，凭证在文件夹「碳盘查2025」里，生成清册和中文报告。

4. Agent 会引导你补齐组织配置与排放因子，并在确认闸处暂停等你签核，全部确认后完成流水线。

### 4.2 Claude Code

Claude Code 原生支持 SKILL.md 格式的 Agent Skill，安装即生效：

1. 下载并解压 `pancarbon.zip`（或 `git clone` 本仓库）；
2. 把解压出的 `pancarbon/` 文件夹放入 Claude Code 的技能目录：

   ```bash
   # 全局（对当前用户的所有项目生效）
   Windows:  %USERPROFILE%\.claude\skills\pancarbon\
   macOS:    ~/.claude/skills/pancarbon/

   # 或项目级（只对该项目生效）
   <项目根目录>\.claude\skills\pancarbon\
   ```

3. 确认 Python 环境可用。建议先手动装一次依赖（Claude Code 执行命令时会使用系统里的 Python）：

   ```bash
   python -m venv .venv
   .venv\Scripts\pip install -r pancarbon\scripts\requirements.txt
   ```

4. 重启 Claude Code 会话后即可唤起。直接说「帮我核算 2025 年温室气体排放并生成清册」，Claude Code 会自动匹配到 `pancarbon` 技能；也可以显式输入 `/pancarbon`。

### 4.3 OpenAI Codex CLI

Codex 通过 `AGENTS.md` 获得项目级指令，把盘碳的规范写进去即可：

1. 把本仓库（或解压后的 `pancarbon/` 文件夹）放在一个固定位置，例如 `D:\tools\PanCarbon\`；
2. 在用户级或项目级 `AGENTS.md`（`~/.codex/AGENTS.md` 或仓库根目录）中加入以下段落：

   ```markdown
   ## 盘碳 PanCarbon：温室气体盘查技能

   当用户要求温室气体盘查、碳核算或核查报告时：

   1. 先完整阅读 pancarbon/SKILL.md，严格遵守其中的九阶段流程与硬性规则；
   2. 命令入口：python pancarbon/scripts/cli.py <command> --run-dir <run 目录>，
      可用命令：init / extract / confirm / classify / match / compute /
      inventory / report / check / deliver / pipeline / deps / audit；
   3. 若依赖未安装，先创建虚拟环境并安装 pancarbon/scripts/requirements.txt；
   4. Stage 2 人工确认闸必须暂停等待用户签核，不得代签；
   5. 模式 B 核查报告仅在用户提供 verification_signoff.json 时输出正式版，
      否则只输出 _draft 草稿。
   ```

3. 重启 Codex 会话后，用自然语言下达盘查任务即可，Codex 会按上述规则执行命令并遵守确认闸。

### 4.4 其他 Agent（通用方法）

任何能读文件、能执行命令的 Agent 都可以使用盘碳，只需在系统提示或项目说明中加入一句话：

> 处理温室气体盘查任务时，先阅读 `<盘碳路径>/pancarbon/SKILL.md`，按其九阶段流程通过 `python pancarbon/scripts/cli.py` 执行，并遵守全部硬性规则。

SKILL.md 是自包含的操作规范，Agent 读完即可正确运行。

### 4.5 给 Agent 的材料清单

无论哪个平台，开始前把以下材料放进一个文件夹并告知 Agent：

- 能源发票：电费、燃气、液化气、柴油等（PDF / Excel / 照片均可）；
- 运输与物流记录（进厂、出厂、厂内转运）；
- 采购、差旅、通勤、废弃物等范围三相关记录；
- 组织基本信息：公司全称、报告年份、分厂/子公司清单；
- 排放因子（如已有官方发布值）。

## 五、本地命令行使用

### 5.0 准备环境（只做一次）

1. 安装 Python 3.10 或更高版本（python.org 下载，安装时勾选 **Add Python to PATH**）；
2. 打开命令行（Windows：`Win + R` 输入 `cmd` 回车，或使用 Git Bash）；
3. 获取本项目（网页 Download ZIP 解压，或 `git clone`）；
4. 在项目根目录（能看到 `pancarbon` 文件夹的那一层）创建虚拟环境并安装依赖：

   ```bash
   # Windows（cmd 或 Git Bash 均可）
   python -m venv .venv
   .venv\Scripts\pip install -r pancarbon\scripts\requirements.txt

   # macOS / Linux 将 .venv\Scripts\ 替换为 .venv/bin/
   ```

5. 环境自检，全部 OK 才继续：

   ```bash
   .venv\Scripts\python pancarbon\scripts\cli.py deps
   ```

> 下文所有命令均在项目根目录执行。为简洁，约定 `%PY%` 代表 `.venv\Scripts\python`（Windows）或 `.venv/bin/python`（macOS/Linux）。

### 5.1 新建运行目录并填写配置

为每次盘查新建一个文件夹（如 `run2025`），复制模板并准备凭证目录：

```bash
copy pancarbon\assets\config_template.json          run2025\org_config.json
copy pancarbon\assets\factor_library_template.json  run2025\factor_library.json
mkdir run2025\vouchers
```

把所有发票、台账、照片放入 `run2025\vouchers`。

**填写 `org_config.json`**：用编辑器打开，把所有 `__REQUIRED__` 替换为真实内容——组织名称、报告年、合并方法、实体清单、气体种类、GWP 版本（建议 AR6）、S2 口径、启用的范围三类别、方法学、报告模式（A=计算报告，B=第三方核查报告，可同时选择）与语言（zh/en）。选择模式 B 时必须填写保证等级、重要性与核查员信息。

**填写 `factor_library.json`**：全流程唯一填写排放因子数值的文件。每条因子需完整填写 7 项：数值 `value`、单位 `unit`、适用条件 `applicability`、来源 `source`、GWP 版本、数据质量 `quality`、量纲 `scale`。因子数值请采用官方发布的最新值（如生态环境部发布的因子库、电网平均排放因子等），并如实填写来源。

### 5.2 初始化校验（Stage 0）

```bash
%PY% pancarbon\scripts\cli.py init --config run2025\org_config.json --run-dir run2025
```

通过后生成 `run2025\config_check.json`。报错时会列出所有未填好的字段路径，按清单修改后重跑。

### 5.3 凭证抽取（Stage 1）

```bash
%PY% pancarbon\scripts\cli.py extract --run-dir run2025 --input-dir run2025\vouchers
```

自动识别 PDF 发票、Excel 台账、zip 压缩包与照片，生成待确认清单 `pending_ledger.json`。注意两点：照片不做自动识别，仅登记为待人工录入项；只有金额没有用量数的行不会擅自折算，需人工补充数量。

### 5.4 人工复核

用编辑器打开 `run2025\pending_ledger.json`，逐行检查：

- 补齐缺失的报告期间（`period_start` / `period_end`）与单位；
- 对月度表中的「金额」「合计」等非排放数据行，标记 `"exclude": true` 排除；
- 为每行补上 `source_key`（排放源编号）、`scope`、`entity_ref` 等分类字段。

### 5.5 签核（Stage 2，不可跳过）

新建 `run2025\batch_signoff.json`，写入签核人信息：

```json
{
  "signed_by": "张三",
  "signed_at": "2026-03-15T10:00:00+08:00"
}
```

执行签核：

```bash
%PY% pancarbon\scripts\cli.py confirm --run-dir run2025 --batch-signoff run2025\batch_signoff.json
```

任何一行未签核都会被拒绝并列出缺签清单。全部通过后生成 `activity_ledger.json`——这是唯一能进入计算的台账文件。

### 5.6 运行流水线（Stage 3 至 9）

```bash
%PY% pancarbon\scripts\cli.py pipeline --run-dir run2025
```

自动依次完成：排放源分类 → 方法与因子匹配 → 计算 → 清册 → 报告 → 勾稽校验 → 交付打包。中途遇到「一源多因子」「单位歧义」等情况会停下等待裁决——这是设计如此（绝不静默取值），按提示处理后重跑即可。

### 5.7 检查结果

- `run2025\checks.json`：`status` 为 `pass` 且无 `ERROR` 才算合格；
- `run2025\ghg_inventory.xlsx`：排放核查清册；
- `run2025\report_A_zh.docx` / `report_A_en.docx`：中英排放报告。

**模式 B（核查报告）说明**：需手工准备 `run2025\verification_signoff.json`（核查员、保证等级、核查声明原文，格式见 `pancarbon\assets\schemas\verification_signoff.schema.json`）后重跑 pipeline，才会输出正式核查报告；否则仅生成 `report_B_*_draft.docx` 草稿，结论段留空。这是合规护栏，工具不会代替核查人员编写保证结论。

### 5.8 获取交付包

校验通过后，最终交付物位于 `run2025\delivery\<run_id>_delivery.zip`，内含清册、报告、图表、带 SHA-256 指纹的交付清单与证据索引（每笔数字可倒查至原始凭证）。

### 学习样例

`example_vouchers_run\` 是从凭证到交付的完整演示（17 个文件），可作为各配置文件的参考模板；`example_run\` 是从标准台账直接进入计算的精简样例。

## 六、产出文件说明

| 文件 | 说明 |
|---|---|
| `ghg_inventory.xlsx` | 排放核查清册：16 个工作表，全公式驱动，含边界、活动数据、因子、计算、数据质量与汇总 |
| `report_A_zh/en.docx` | 模式 A 排放计算报告（ISO 14064-1 + GHG Protocol 口径），中英各一份 |
| `report_B_zh/en.docx` | 模式 B 第三方核查报告（ISO 14064-3 口径）；无签核时输出 `_draft` 草稿 |
| `results.json` | 机器可读的计算结果，含逐行计算血缘，可倒查 |
| `checks.json` | 20 条勾稽规则的校验报告（V01–V20） |
| `activity_ledger.json` | 已签核的活动数据台账，计算核心的唯一输入 |
| `evidence_index.json` | 证据索引：每笔排放量对应哪张原始凭证 |
| `delivery_manifest.json` | 交付清单：每个文件的字节数与 SHA-256 指纹 |
| `delivery/<run_id>_delivery.zip` | 最终交付包 |

## 七、常见问题与报错排查

**Q1：双击 cli.py 没有反应？**
这是命令行工具，不通过双击运行。请按 5.0 节打开命令行，完整输入命令。

**Q2：`init` 报错提示大量 `__REQUIRED__`？**
说明 `org_config.json` 的占位符未填写完整。报错信息会列出全部缺失字段及路径，逐个填写后重跑。

**Q3：`confirm` 退出码为 2？**
存在未签核或信息不全的行。查看输出的 `unsigned[]` 清单，回到 5.4 节补齐后重新签核。

**Q4：`pipeline` 中途停止？**
不是故障，而是「遇歧义必上报」的设计。例如同一活动匹配到多个候选因子时，工具会列出候选等待裁决，处理完成后重跑 pipeline。

**Q5：计算结果与预期相差 1000 倍？**
通常是因子单位量纲（`scale`）填写错误。统一公式为 `tco2e = 活动数据 × 因子 × GWP ÷ scale`，`scale` 必须与因子单位严格对应（如因子单位为 kgCO2/t，则 scale 为 1000）。

**Q6：模式 B 报告为什么只有 `_draft` 草稿？**
缺少核查签核文件。核查结论必须由具备资质的核查人员签署（见 5.7 节），工具不会代写。

**Q7：数据填错后如何重算？**
修正台账后重跑 `confirm` 与 `pipeline`。计算支持多版本：`compute --append --version-id V2 --status draft` 可追加版本，同一时间仅允许一个版本为 final，旧版本自动转为 superseded。

**Q8：校验存在 ERROR 时能否交付？**
不能。任何 ERROR 级发现都会阻断交付（`deliver` 返回 `blocked`），修正后重跑方可通过。

**Q9：为什么包内没有排放因子？**
有意为之。排放因子具有地域与时效性，内置会过时且有合规风险。请按 5.1 节注入官方发布的最新因子。

**Q10：图片发票能自动识别吗？**
本地路线不做 OCR，需人工录入；在 Agent 路线中可由 AI 视觉识别为候选值，仍需人工确认签核。

## 八、安全与合规须知

- 本工具输出为**辅助核算结果**，不构成正式的第三方核查意见；模式 B 核查声明必须由具备资质的核查人员签核后方可对外发布。
- 包内不含任何真实企业数据、排放因子数值或报告文字，所有数值来自运行时配置。请勿将真实数据或因子提交回本仓库。
- 交付包内所有文件带 SHA-256 指纹与 AIGC（人工智能生成内容）声明，便于归档与追溯。

## 九、技术架构

- **九阶段流水线**：配置校验 → 凭证抽取 → 人工确认闸 → 排放源分类 → 方法与因子匹配 → 计算 → 清册 → 报告 → 勾稽校验 → 交付打包。Stage 1/2 刻意不纳入自动流水线，中间必须有人签核。
- **可插拔凭证抽取**：PDF 发票（pypdf）、Excel 台账（openpyxl/xlrd）、zip 包（中文文件名 cp437→gbk 还原）、图片凭证四类抽取器，字段别名与期间规则由 `extraction_rules.json` 配置。
- **统一计算公式**：`tco2e = ad × ef × gwp / scale`，Decimal 精确计算、逐行血缘；量纲契约 `scale_matches()` 自动复核。
- **双轨对账**：清册公式由公式引擎重算，与 Decimal 纯函数结果逐格比对（容差 1e-9）；公式重算按 LibreOffice → formulas → 内置求值器 → ERROR 四级降级。
- **V01–V20 校验规则**：数值勾稽、量纲、签核闸、启发式禁令（禁止「取最大值当合计」）、CN/EN 一致性、模式 B 签核护栏、未解析占位符、交付完整性等。
- **中英双语报告**：动态数值只进表格单元格，散文使用一一对应的固定话术（`phrases.json`），保证中英数值逐项可对账。

完整操作规范见 [`pancarbon/SKILL.md`](pancarbon/SKILL.md)，配置文件字段字典见 [`pancarbon/references/schemas.md`](pancarbon/references/schemas.md)。

## 十、参与贡献与许可

```
PanCarbon/
├── pancarbon/                  # Skill 包本体
│   ├── SKILL.md                # 操作规范（Agent 与维护者共读）
│   ├── scripts/                # 九阶段流水线 CLI 与各阶段实现
│   ├── assets/                 # 模板、话术、六份 JSON Schema
│   ├── references/             # 标准映射、方法学、校验规则等文档
│   └── tests/                  # 6 套里程碑测试，102 项断言
├── example_run/                # 标准台账直入的端到端演示（合成数据）
└── example_vouchers_run/       # 从原始凭证出发的端到端演示（合成数据）
```

- 测试：`.venv\Scripts\python pancarbon\tests\test_m0.py`（m0 至 m5 共 6 套）。
- 欢迎通过 Issue 与 Pull Request 参与改进。
- 本项目以 [MIT License](LICENSE) 开源。

---

<div align="center">

**PanCarbon** — Audit-grade organizational GHG inventory & verification per GHG Protocol & ISO 14064

vouchers in · signed ledger · formula-driven inventory · bilingual reports out

</div>
