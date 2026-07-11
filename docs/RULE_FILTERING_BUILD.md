# 基础成药性规则过滤开发文档

日期：2026-07-09

范围：在候选分子完成导入和结构校验之后，新增一层可追踪、可重复运行的基础规则过滤。当前阶段覆盖 Lipinski/Veber 类硬规则和 RDKit FilterCatalog 告警接口，为后续 Docking、ADMET、Advisor 和报告模块提供更干净的候选分子入口。

## 1. 本阶段目标

上游流程目前已经可以完成：

```text
上传文件
  -> 解析 seed_ligands
  -> 导入 molecules
  -> 校验 molecules
  -> 写入 molecule_properties
```

本阶段把下一道质量门接上：

```text
molecule_properties
  -> 基础规则过滤
  -> 写入 rule_filter_results
  -> 更新 molecule.status / molecule.labels
  -> 后续 Docking / ADMET / DecisionCard / Report
```

实现后，系统可以：

- 对项目下所有候选分子批量执行规则过滤。
- 区分 `passed`、`failed`、`skipped_invalid_structure`、`needs_properties` 等结果。
- 把每个分子的过滤结果写入 `rule_filter_results`。
- 重复运行时更新已有结果，不重复创建记录。
- 查询项目级或单分子级过滤结果。
- 在 RDKit 可用时读取 PAINS/BRENK FilterCatalog 告警；不可用时保留 warning，不阻断主流程。

## 2. 新增和修改文件

| 文件 | 作用 |
|---|---|
| `src/medagent/services/rule_filtering.py` | 新增基础规则过滤服务、结果 upsert、分子状态更新 |
| `src/medagent/services/rdkit_adapter.py` | 增加 RDKit FilterCatalog 适配，并兼容 RDKit 缺失场景 |
| `src/medagent/domain/schemas.py` | 新增 `RuleFilterResponse` 和 `RuleFilterResultRead` |
| `src/medagent/api/app.py` | 新增规则过滤执行 API、项目级结果查询、分子级结果查询 |
| `tests/test_rule_filtering.py` | 覆盖通过、失败、跳过、查询和幂等行为 |
| `docs/RULE_FILTERING_BUILD.md` | 本开发文档 |

## 3. 新增 API

### 3.1 执行基础规则过滤

```http
POST /projects/{project_id}/molecules/filter-rules
```

用途：对项目下所有 `molecules` 执行基础规则过滤。

响应示例：

```json
{
  "rule_set": "basic_drug_likeness_v1",
  "evaluated_count": 2,
  "passed_count": 1,
  "failed_count": 1,
  "skipped_count": 1,
  "result_ids": ["FILTER-..."],
  "passed_molecule_ids": ["MOL-..."],
  "failed_molecule_ids": ["MOL-..."],
  "skipped_molecule_ids": ["MOL-..."]
}
```

### 3.2 查询项目级过滤结果

```http
GET /projects/{project_id}/rule-filter-results
```

用途：返回项目下所有分子的过滤结果，按创建时间和数据库 id 排序。

### 3.3 查询单分子过滤结果

```http
GET /projects/{project_id}/molecules/{molecule_id}/rule-filter-results
```

用途：返回某个候选分子的过滤结果。当前每个分子每个规则集只有一条结果，但接口返回数组，方便后续同时支持多个规则集版本。

## 4. 规则集

当前规则集名称：

```text
basic_drug_likeness_v1
```

规则来源分为两类。

### 4.1 描述符阈值规则

| 字段 | 阈值 | 失败标签 |
|---|---:|---|
| `mw` | `<= 500` | `lipinski_mw_gt_500` |
| `logp` | `<= 5` | `lipinski_logp_gt_5` |
| `hbd` | `<= 5` | `lipinski_hbd_gt_5` |
| `hba` | `<= 10` | `lipinski_hba_gt_10` |
| `tpsa` | `<= 140` | `veber_tpsa_gt_140` |
| `rotatable_bond_count` | `<= 10` | `veber_rotatable_bonds_gt_10` |

如果某个字段缺失，会写入 warning，例如：

```text
missing_logp
missing_tpsa
missing_rotatable_bond_count
```

字段缺失本身不会直接导致失败，因为当前轻量校验模式下并不一定能得到完整 RDKit 描述符。

### 4.2 RDKit FilterCatalog 告警

当 RDKit 可用时，服务会尝试加载：

```text
PAINS_A
PAINS_B
PAINS_C
BRENK
```

命中的告警会写入失败规则：

```text
rdkit_alert:<description>
```

不同 RDKit 版本可能缺少部分 catalog 枚举，所以适配器使用兼容式加载：存在就加入，不存在就跳过。RDKit 完全不可用时，过滤结果不会中断，而是加入：

```text
rdkit_filter_catalog_unavailable
```

## 5. 分子状态变化

### 5.1 通过规则过滤

条件：没有失败规则。

```text
status = passed_filter
labels += ["rule_filter_evaluated", "rule_filter_passed"]
```

如果存在缺失字段 warning，也会追加：

```text
rule_filter_incomplete
```

### 5.2 未通过规则过滤

条件：至少命中一个失败规则。

```text
status = failed_filter
labels += ["rule_filter_evaluated", "rule_filter_failed", "<failed_rule>"]
```

### 5.3 跳过非法结构

条件：分子状态已经是 `invalid_structure`。

```text
decision = skipped_invalid_structure
labels += ["rule_filter_skipped"]
```

### 5.4 缺少性质记录

条件：分子还没有对应 `molecule_properties`。

```text
decision = needs_properties
labels += ["rule_filter_needs_properties"]
```

这种情况不会计入 `evaluated_count`，会计入 `skipped_count`。

## 6. 数据库写入

规则结果写入 `rule_filter_results`：

| 字段 | 内容 |
|---|---|
| `filter_result_id` | 业务 id，前缀 `FILTER` |
| `project_id` | 项目 id |
| `molecule_id` | 分子 id |
| `rule_set` | 当前为 `basic_drug_likeness_v1` |
| `decision` | `passed` / `failed` / `skipped_invalid_structure` / `needs_properties` |
| `failed_rules` | 命中的失败规则列表 |
| `warnings` | 缺失字段、RDKit 不可用等提示 |
| `labels` | 本次过滤生成的标签 |
| `properties_snapshot` | 过滤时读取到的性质快照 |
| `raw_output` | RDKit catalog 可用性和命中详情 |

幂等键：

```text
molecule_id + rule_set
```

重复调用过滤 API 会更新已有记录，并返回相同的 `filter_result_id`。

## 7. 当前测试覆盖

新增测试文件：

```text
tests/test_rule_filtering.py
```

覆盖内容：

- `CCO` 校验后进入规则过滤，结果为 `passed_filter`。
- 超长烷烃命中 `lipinski_mw_gt_500`，结果为 `failed_filter`。
- 非法 SMILES `C1CC` 保持 `invalid_structure`，过滤结果为 `skipped_invalid_structure`。
- 项目级过滤结果查询返回 3 条结果。
- 单分子过滤结果查询返回对应分子的结果。
- 重复执行过滤不重复创建 `rule_filter_results`。

本轮已执行：

```text
python -m pytest tests/test_rule_filtering.py -q
python -m pytest tests/test_molecule_validation.py -q
python -m pytest -q
```

结果：

```text
21 passed, 1 warning
```

warning 来自 FastAPI/TestClient 依赖链中的 Starlette deprecation，不是本轮业务代码失败。

## 8. 已知限制

- 当前规则阈值是基础成药性过滤，不等价于真实项目的最终筛选标准。
- 如果没有安装 RDKit，PAINS/BRENK 告警不会执行，只会留下 `rdkit_filter_catalog_unavailable` warning。
- 当前还没有按靶点类型、给药方式、组织分布或 CNS 暴露要求做差异化规则集。
- 规则结果还没有直接并入 DecisionCard，后续可以把 `rule_filter_results` 作为卡片生成的重要证据来源。

## 9. 下一步建议

推荐下一阶段做“规则过滤结果进入决策卡和报告”：

1. 让 `decision_cards` 读取 `rule_filter_results`，为 `passed_filter` 和 `failed_filter` 生成更准确的推荐。
2. 在 `/projects/{project_id}/report` 的 `filtering_statistics` 区块中加入通过率、失败原因分布和候选分子清单。
3. 为后续 Docking 阶段只选择 `passed_filter` 分子提供统一入口。
4. 再往后接入 ADMET 预测时，可以把规则过滤结果作为第一层快速排除，减少昂贵工具调用数量。
