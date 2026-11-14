# 盘碳 PanCarbon — 组织温室气体排放核查工具

> **盘碳**，谐音「盘查」——把组织一年的碳排放，盘成一本经得起审计的账。

盘碳依据 **GHG Protocol（温室气体核算体系）** 与 **ISO 14064-1/-3** 标准，帮助你完成组织层面的温室气体排放核算与核查：你提供一年内的用电、用气、运输、采购等使用数据和凭证，它算出对应的二氧化碳当量排放（tCO2e），生成带公式的 Excel 排放清册和中英双语的排放报告或核查报告。

> **纯抽象通用框架**：包内不含任何真实企业数据、排放因子数值或报告模板文字。组织边界、报告年、实体清单、排放因子库、方法学与保证等级全部由运行时配置注入。

---

## 目录

1. [这是做什么的？（通俗版）](#1-这是做什么的通俗版)
2. [名词小课堂](#2-名词小课堂)
3. [开始之前：两种使用方式怎么选](#3-开始之前两种使用方式怎么选)
4. [路线一：在 WorkBuddy 中使用（推荐，最简单）](#4-路线一在-workbuddy-中使用推荐最简单)
5. [路线二：本地命令行使用（保姆级教学）](#5-路线二本地命令行使用保姆级教学)
6. [产出文件说明](#6-产出文件说明)
7. [常见问题与报错排查](#7-常见问题与报错排查)
8. [安全与合规须知](#8-安全与合规须知)
9. [技术架构（进阶）](#9-技术架构进阶)
10. [参与贡献与许可](#10-参与贡献与许可)

---

## 1. 这是做什么的？（通俗版）

把碳盘查想象成「给公司的碳排放记账、出报表、请人审计」三件事：

```
你收集的原始单据          盘碳自动做的事                你最终拿到的东西
─────────────────        ─────────────────────────     ─────────────────────
电费发票   ─┐
燃气发票   ─┤            ① 识别单据里的用量和日期        ① 排放核查清册（Excel，
运输记录   ─┼── 交给盘碳 ──> ② 人工确认一遍数据          16 个工作表、全公式）
采购/差旅  ─┤            ③ 匹配排放因子并计算           ② 排放报告或核查报告
照片/扫描件 ─┘            ④ 20 道勾稽校验防止算错        （Word，中英各一份）
                          ⑤ 打包交付、每份文件带指纹      ③ 校验报告 + 交付清单
```

它和普通计算器最大的不同，是**专为「经得起第三方核查」设计的**：

- 每一行数据都必须有人签名确认才允许进入计算（不可绕过）；
- 每一笔结果都能倒查回最初的那张发票；
- 20 条勾稽规则自动检查算术、单位、中英报告是否一致，有错坚决不放行；
- 报告如需正式核查结论，必须由具备资质的核查人员签署，工具绝不代写。

## 2. 名词小课堂

| 名词 | 通俗解释 |
|---|---|
| **温室气体（GHG）** | 会造成温室效应的气体，主要是二氧化碳（CO2）、甲烷（CH4）等 |
| **范围一（Scope 1）** | 公司自己烧的：自有锅炉烧燃气、自有卡车烧柴油 |
| **范围二（Scope 2）** | 别人烧、你买的：外购电力、外购热力/蒸汽 |
| **范围三（Scope 3）** | 上下游的：原材料采购、物流运输、员工差旅通勤、废弃物处理等 15 类 |
| **活动数据（ad）** | 用了多少：用了 5000 度电、烧了 2 吨柴油 |
| **排放因子（ef）** | 每单位活动对应的排放：每度电约 0.5562 kgCO2（示例，以官方发布为准） |
| **GWP** | 全球变暖潜势，把甲烷等气体折算成「等量的二氧化碳」的倍数 |
| **tCO2e** | 吨二氧化碳当量，所有温室气体统一折算后的计量单位 |
| **排放清册（Inventory）** | 全部排放的明细账本，Excel 表格形式 |
| **签核** | 签名确认「这条数据我核对过、属实」。盘碳要求每行数据都签核 |
| **排放因子库** | 存放排放因子数值的文件。盘碳包内**不含任何因子数值**，由你自己按官方发布填写 |

## 3. 开始之前：两种使用方式怎么选

| | 路线一：WorkBuddy 中使用 | 路线二：本地命令行 |
|---|---|---|
| 适合谁 | 不想碰命令行的大多数用户 | 想要完全掌控、批量处理或集成到自己流程的技术用户 |
| 需要准备 | 一个 WorkBuddy 账号即可 | 安装 Python 3.10 以上 |
| 上手难度 | 很低：导入 Skill 包，然后像聊天一样用 | 中等：照抄本文命令即可 |
| 原理 | WorkBuddy 里的 AI 助手替你执行盘碳的命令 | 你自己逐条执行盘碳的命令 |

两条路线用的是**同一套计算引擎**，结果完全一致。

## 4. 路线一：在 WorkBuddy 中使用（推荐，最简单）

### 第 1 步：下载 Skill 包

在本仓库的 [Releases 页面](https://github.com/Yorking6/PanCarbon/releases) 下载最新版本的 `pancarbon.zip`，**不需要解压**。

### 第 2 步：导入 WorkBuddy

打开 WorkBuddy，进入技能（Skill）管理界面，选择「安装本地 Skill / 从文件导入」，选中刚才下载的 `pancarbon.zip`，确认安装。安装成功后，对话里就能唤起盘碳了。

### 第 3 步：准备材料并开始对话

把下面的材料放进一个文件夹（比如桌面新建 `碳盘查2025`）：

- 能源发票：电费、燃气、液化气、柴油等（PDF/Excel/照片都行）
- 运输与物流记录（进厂、出厂、厂内转运）
- 采购、差旅、通勤、废弃物等范围三相关记录
- 组织基本信息：公司全称、报告年份（如 2025）、有哪些分厂/子公司

然后在 WorkBuddy 对话框里直接说，例如：

> 请用盘碳 Skill，帮我核算我司 2025 年度的温室气体排放。凭证都在文件夹「碳盘查2025」里，生成清册和中文报告。

AI 助手会引导你补齐组织配置和排放因子，跑完整个流程，最后把清册、报告和交付包给你。

### 第 4 步：务必人工把关

无论哪条路线，**「人工确认闸」都会要求你对每一行数据签名确认**——这是本工具的合规底线。AI 会把待确认清单给你，你需要核对数字、补齐缺失的日期或单位、排除非排放数据行，然后确认签核。请务必逐条看完再确认，不要一键全签。

## 5. 路线二：本地命令行使用（保姆级教学）

### 5.0 准备环境（只做一次）

1. 安装 Python 3.10 或更高版本（python.org 下载，安装时勾选 **Add Python to PATH**）。
2. 打开命令行（Windows：按 `Win + R`，输入 `cmd` 回车；或用 Git Bash）。
3. 下载本项目（点仓库绿色 Code 按钮 → Download ZIP 解压，或执行 `git clone`）。
4. 在项目根目录（能看到 `pancarbon` 文件夹的那一层）创建虚拟环境并装依赖：

```bash
# Windows（cmd 或 Git Bash 均可）
python -m venv .venv
.venv\Scripts\pip install -r pancarbon\scripts\requirements.txt
```

macOS / Linux 用户把 `.venv\Scripts\` 换成 `.venv/bin/`。

5. 环境自检（显示全部 OK 才继续）：

```bash
.venv\Scripts\python pancarbon\scripts\cli.py deps
```

> 下文所有命令都在项目根目录执行。为省字数，约定 `%PY%` 代表 `.venv\Scripts\python`（Windows）或 `.venv/bin/python`（macOS/Linux）。

### 5.1 新建运行目录并填写配置（Stage 0 前置）

为每一次盘查新建一个文件夹，例如 `run2025`。然后复制两份模板进去：

```bash
copy pancarbon\assets\config_template.json          run2025\org_config.json
copy pancarbon\assets\factor_library_template.json  run2025\factor_library.json
mkdir run2025\vouchers
```

把所有发票、台账、照片放进 `run2025\vouchers`。

**填写 `org_config.json`**（用记事本或 VS Code 打开）：把文件里所有 `__REQUIRED__` 字样替换成真实内容——组织名称、报告年、合并方法、实体清单、气体种类、GWP 版本（建议 AR6）、S2 口径、启用的范围三类别、方法学、报告模式（A=计算报告，B=第三方核查报告，可都要）与语言（zh/en）。**要做模式 B 就必须填保证等级、重要性和核查员信息**。

**填写 `factor_library.json`**：这是全流程唯一填排放因子数值的地方。每条因子都要写全 7 项：数值 `value`、单位 `unit`、适用条件 `applicability`、来源 `source`、GWP 版本、数据质量 `quality`、量纲 `scale`。因子数值请采用官方发布的最新值（如生态环境部发布的因子库、电网平均排放因子等），并如实填写来源。

### 5.2 初始化校验（Stage 0）

```bash
%PY% pancarbon\scripts\cli.py init --config run2025\org_config.json --run-dir run2025
```

通过后生成 `run2025\config_check.json`。**报错时会列出所有没填好的字段**，按清单改完重跑即可。

### 5.3 凭证抽取（Stage 1）

```bash
%PY% pancarbon\scripts\cli.py extract --run-dir run2025 --input-dir run2025\vouchers
```

自动识别 PDF 发票、Excel 台账、zip 压缩包和照片，生成待确认清单 `pending_ledger.json`。注意：

- 照片**不做自动识别（OCR）**，只会登记为待人工录入项；
- 只有金额、没有用量数的行**不会擅自折算**，需要你人工补数量。

### 5.4 人工复核（整个流程最关键的一步）

用编辑器打开 `run2025\pending_ledger.json`，逐行检查：

- 缺报告期间（`period_start` / `period_end`）的行 → 补上起止日期；
- 缺单位或归一化数值的行 → 补齐；
- 月度表里的「金额」「合计」等非排放数据行 → 加 `"exclude": true` 排除；
- 每行补上 `source_key`（排放源编号）、`scope`、`entity_ref` 等分类字段。

### 5.5 签核（Stage 2，不可跳过）

新建 `run2025\batch_signoff.json`，写入你的署名（示例）：

```json
{
  "signed_by": "张三",
  "signed_at": "2026-03-15T10:00:00+08:00"
}
```

执行：

```bash
%PY% pancarbon\scripts\cli.py confirm --run-dir run2025 --batch-signoff run2025\batch_signoff.json
```

**任何一行没签核都会被拒绝**，并列出缺签清单。全部通过后生成 `activity_ledger.json`——只有这份文件能进入计算。

### 5.6 一键运行流水线（Stage 3 至 9）

```bash
%PY% pancarbon\scripts\cli.py pipeline --run-dir run2025
```

自动依次完成：排放源分类 → 方法与因子匹配 → 计算 → 生成清册 → 生成报告 → 20 条勾稽校验 → 交付打包。中途遇到「一源多因子」「单位歧义」等情况会**停下来等你裁决**，这是设计如此（绝不瞎猜），按报错提示处理后重跑即可。

### 5.7 检查结果

- 打开 `run2025\checks.json`：`status` 为 `pass` 且无 `ERROR` 才算合格；
- 打开 `run2025\ghg_inventory.xlsx`：这就是排放核查清册；
- 打开 `run2025\report_A_zh.docx` / `report_A_en.docx`：中英排放报告。

**模式 B（核查报告）特别说明**：需要你手工准备 `run2025\verification_signoff.json`（核查员、保证等级、核查声明原文，格式见 `pancarbon\assets\schemas\verification_signoff.schema.json`）后再跑一次 pipeline，才会输出正式核查报告；否则只会生成 `report_B_*_draft.docx` 草稿，结论段留空。**这是合规护栏：工具绝不代替核查人员编写保证结论。**

### 5.8 拿走交付包

校验通过后，最终交付物在 `run2025\delivery\<run_id>_delivery.zip`，内含清册、报告、图表、带 SHA-256 指纹的交付清单和证据索引（每笔数字都能倒查到原始凭证）。

### 学习样例

不想自己造数据？`example_vouchers_run\` 文件夹里有从凭证到交付的**全套 17 个文件**，是最完整的参考模板；`example_run\` 是从标准台账直接进入计算的精简样例。

## 6. 产出文件说明

| 文件 | 是什么 |
|---|---|
| `ghg_inventory.xlsx` | 排放核查清册：16 个工作表，全部公式驱动，含边界、活动数据、因子、计算、数据质量与汇总 |
| `report_A_zh/en.docx` | 模式 A 排放计算报告（ISO 14064-1 + GHG Protocol 口径），中英各一份 |
| `report_B_zh/en.docx` | 模式 B 第三方核查报告（ISO 14064-3 口径）；无签核时输出 `_draft` 草稿 |
| `results.json` | 机器可读的计算结果，含每一行的计算过程（可倒查） |
| `checks.json` | 20 条勾稽规则的校验报告（V01 到 V20） |
| `activity_ledger.json` | 已签核的活动数据台账（计算核心的唯一输入） |
| `evidence_index.json` | 证据索引：每笔排放量对应哪张原始凭证 |
| `delivery_manifest.json` | 交付清单：每个文件的字节数与 SHA-256 指纹 |
| `delivery/<run_id>_delivery.zip` | 最终交付包 |

## 7. 常见问题与报错排查

**Q1：双击 cli.py 没反应？**
这是命令行工具，不是双击运行的。请按 5.0 节打开命令行，把命令完整敲进去。

**Q2：`init` 报错，说有很多 `__REQUIRED__`？**
说明 `org_config.json` 里的占位符没填完。报错信息会列出**全部**缺的字段和路径，逐个填好再跑。

**Q3：`confirm` 退出码是 2？**
有行没签核或信息不全。看输出的 `unsigned[]` 清单，回到 5.4 节补齐后再签核。

**Q4：`pipeline` 跑一半停了？**
不是坏了，是「遇歧义必上报」的设计。比如同一活动匹配到两个候选排放因子，工具会列出候选等你选，处理完重跑 pipeline。

**Q5：为什么我的因子算出来差了 1000 倍？**
大概率是因子单位量纲（`scale`）填错。盘碳统一公式为 `tco2e = 活动数据 × 因子 × GWP ÷ scale`，`scale` 必须和因子单位严格对应（如因子是 kgCO2/t，scale 就是 1000）。填对单位契约即可。

**Q6：模式 B 报告为什么只有 `_draft` 草稿？**
因为还没有核查签核文件。核查结论必须由具备资质的核查人员签署（见 5.7 节），工具不会代写。

**Q7：发现填错数据，想重算怎么办？**
改正台账后重跑 `confirm` 和 `pipeline` 即可。计算支持多版本：`compute --append --version-id V2 --status draft` 可追加版本，但**同一时间只允许一个版本为 final（正式）**，旧版本自动转为 superseded（被取代）。

**Q8：校验有 ERROR，能先交付吗？**
不能。任何 ERROR 级发现都会阻断交付（`deliver` 返回 `blocked`），必须修正后重跑。这是为了确保交出去的东西对得上账。

**Q9：包里怎么没有排放因子？能不能内置一份？**
不能，这是有意为之。排放因子有地域和时效性（各国、各年发布值不同），内置会很快过时且有合规风险。请按 5.1 节自行注入官方发布的最新因子。

**Q10：图片发票能自动识别吗？**
本地路线不做 OCR，需要人工录入（或在 WorkBuddy 路线中由 AI 助手视觉识别为候选值，仍需你确认签核）。

## 8. 安全与合规须知

- 本工具输出为**辅助核算结果**，不构成正式的第三方核查意见；模式 B 核查声明必须由具备资质的核查人员签核后方可对外发布。
- 包内不含任何真实企业数据、排放因子数值或报告文字，所有数值来自运行时配置——请勿把真实数据或因子提交回本仓库。
- 交付包内所有文件带 SHA-256 指纹和 AIGC（人工智能生成内容）声明，便于归档与追溯。

## 9. 技术架构（进阶）

- **九阶段流水线**：配置校验 → 凭证抽取 → 人工确认闸 → 排放源分类 → 方法与因子匹配 → 计算 → 清册 → 报告 → 勾稽校验 → 交付打包（Stage 1/2 刻意不进自动流水线，必须有人签核）。
- **可插拔凭证抽取**：PDF 发票（pypdf）、Excel 台账（openpyxl/xlrd）、zip 包（中文文件名 cp437→gbk 还原）、图片凭证四类抽取器。
- **统一计算公式**：`tco2e = ad × ef × gwp / scale`，Decimal 精确计算、逐行血缘；量纲契约 `scale_matches()` 复核，专治「多除 1000」类事故。
- **双轨对账**：清册里的公式会用公式引擎重算一遍，与 Decimal 纯函数结果逐格比对（容差 1e-9）；LibreOffice → formulas → 内置求值器四级降级。
- **V01–V20 校验规则**：数值勾稽、量纲、签核闸、启发式禁令（禁止「取最大值当合计」）、CN/EN 一致性、模式 B 签核护栏、未解析占位符、交付完整性等。
- **中英双语报告**：动态数值只进表格单元格，散文使用一一对应的固定话术（`phrases.json`），保证中英数值逐项可对账。

完整规范见 [`pancarbon/SKILL.md`](pancarbon/SKILL.md)，各配置文件的字段字典见 [`pancarbon/references/schemas.md`](pancarbon/references/schemas.md)。

## 10. 参与贡献与许可

- 目录结构：`pancarbon/` 为 Skill 包本体（SKILL.md + scripts + references + assets + tests，57 个文件）；`example_run/` 与 `example_vouchers_run/` 为端到端合成数据演示。
- 测试：`.venv\Scripts\python pancarbon\tests\test_m0.py`（共 6 套，m0 至 m5，102 项测试）。
- 欢迎通过 Issue 与 Pull Request 参与改进。
- 本项目以 [MIT License](LICENSE) 开源。

---

**PanCarbon — Audit-grade organizational GHG inventory & verification per GHG Protocol & ISO 14064: vouchers in, signed ledger, formula-driven inventory and bilingual reports out.**
