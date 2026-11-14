# ghg-inventory-verification — 组织温室气体排放核查 Agent Skill

依据 **GHG Protocol** 与 **ISO 14064-1/-3** 完成组织温室气体排放核算与核查的 Agent Skill。把「原始凭证 → 活动数据 → 方法与排放因子 → tCO2e → 排放核查清册 → 核查报告」变成一条可复现、可追溯、可校验的流水线。

> ⚠️ **纯抽象通用框架**：包内不含任何真实企业数据、排放因子数值或报告模板文字。组织边界、报告年、实体清单、排放因子库、方法学与保证等级全部由运行时配置注入。

## 功能特性

- **9 阶段流水线**：配置校验 → 凭证抽取 → 人工确认闸 → 排放源分类 → 方法与因子匹配 → 计算 → 清册 → 报告 → 勾稽校验 → 交付打包
- **可插拔凭证抽取**：PDF 发票 / Excel 台账 / zip 包 / 图片凭证（含 Agent 视觉录入候选）
- **人工签核闸不可绕过**：每行活动数据必须人工签核后才能进入计算
- **统一计算公式**：`tco2e = ad × ef × gwp / scale`，量纲契约由因子库显式声明
- **带公式 xlsx 清册**：16 个工作表、全公式驱动、双轨对账（Decimal 纯函数 + 公式重算）
- **中英双模式报告**：模式 A（ISO 14064-1 计算报告）/ 模式 B（ISO 14064-3 核查报告，无签核只出草稿）
- **V01–V20 勾稽校验**：数值勾稽、量纲、签核闸、启发式禁令、CN/EN 一致性、公式重算、交付完整性
- **SHA-256 交付清单**：证据索引、文件指纹、AIGC 声明

## 目录结构

```
ghg-inventory-verification/   # Skill 包本体（SKILL.md + scripts + references + assets + tests）
example_run/                  # 标准化台账直入的端到端演示（合成数据）
example_vouchers_run/         # 从原始凭证出发的端到端演示（合成数据，17 个文件全流程）
```

## 环境要求

- Python ≥ 3.10（建议 3.13）
- 依赖见 `ghg-inventory-verification/scripts/requirements.txt`，**必须安装在 Skill 包之外的独立虚拟环境**

```bash
python -m venv .venv
.venv\Scripts\pip install -r ghg-inventory-verification\scripts\requirements.txt
```

## 快速开始

```bash
# 0. 环境自检
python ghg-inventory-verification/scripts/cli.py deps

# 1. 复制 assets/config_template.json 与 assets/factor_library_template.json
#    到运行目录，填写 org_config.json 与 factor_library.json，然后：
python ghg-inventory-verification/scripts/cli.py init --config <run>/org_config.json --run-dir <run>

# 2. 凭证抽取 → 待确认台账
python ghg-inventory-verification/scripts/cli.py extract --run-dir <run> --input-dir <run>/vouchers

# 3. 人工复核 pending_ledger.json 后批量签核 → activity_ledger.json
python ghg-inventory-verification/scripts/cli.py confirm --run-dir <run> --batch-signoff <run>/batch_signoff.json

# 4. 一键流水线：分类 → 匹配 → 计算 → 清册 → 报告 → 校验 → 交付
python ghg-inventory-verification/scripts/cli.py pipeline --run-dir <run>
```

校验通过后，交付包位于 `<run>/delivery/<run_id>_delivery.zip`。完整命令表与运行约定见 `ghg-inventory-verification/SKILL.md`。

## 核心纪律

1. **人工确认闸不可绕过**：所有活动数据必须逐行签核，Skill 不代签、不推断
2. **不伪造核查结论**：模式 B 无授权签核只生成 `*_draft.docx`，结论段保留占位符
3. **不静默取值**：因子歧义、量纲不符一律上报候选集，绝不静默填 0
4. **不硬编码量纲除数**：`scale` 必须由因子库单位契约显式给出

## 免责声明

本工具输出为辅助核算结果，不构成正式的第三方核查意见。模式 B 核查声明必须由具备资质的核查人员签核后方可对外发布。

## License

MIT
