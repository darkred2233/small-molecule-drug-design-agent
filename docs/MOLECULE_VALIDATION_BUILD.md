# 分子轻量校验与性质估算开发文档

日期：2026-07-07

范围：在 RAG 暂不开发的前提下，继续完善候选分子进入后续计算流程前的基础质量门控。本阶段实现轻量 SMILES 结构校验、候选分子状态更新、基础性质估算入库和查询 API。

> 重要说明：本阶段不是 RDKit 级别的真实化学结构校验。它只做括号、方括号、环编号、字符集和元素计数等轻量规则检查，用于让项目主流程先跑通。后续接入 RDKit/Datamol 后，需要用真实 molecule parser、标准化、盐拆分、互变异构处理、性质计算和 PAINS/反应性基团过滤替换或增强当前逻辑。

## 1. 本阶段目标

上一阶段已经实现：

- 上传 `.smi`、`.smiles`、`.txt`、`.csv`、`.sdf`、`.pdb` 文件。
- 从文件解析 `seed_ligands`。
- 将 `seed_ligands` 导入 `molecules` 候选分子表。

本阶段补上 `molecules` 后面的第一道质量门：

```text
上传文件
  -> 解析 seed_ligands
  -> 导入 molecules
  -> 轻量校验 molecules
  -> 写入 molecule_properties
  -> 后续 RDKit / Docking / ADMET / Advisor
```

实现后，系统可以：

- 对项目下所有候选分子批量执行轻量校验。
- 将通过校验的分子状态改为 `structure_validated`。
- 将结构异常的分子状态改为 `invalid_structure`。
- 为通过校验的分子写入或更新 `molecule_properties`。
- 通过 API 查询单个分子的性质记录。
- 第二次重复运行校验时保持幂等，不重复创建性质记录。

## 2. 新增文件与修改文件

| 文件 | 作用 |
|---|---|
| `src/medagent/services/molecule_validation.py` | 新增轻量 SMILES 校验和性质估算服务 |
| `src/medagent/domain/schemas.py` | 新增校验响应和性质响应 Pydantic Schema |
| `src/medagent/api/app.py` | 新增分子校验 API、分子性质查询 API，并更新中文 `/docs` 页面 |
| `tests/test_molecule_validation.py` | 新增校验、性质写入、状态更新和幂等性测试 |
| `docs/MOLECULE_VALIDATION_BUILD.md` | 本文档 |

## 3. 数据库写入设计

### 3.1 使用的已有表

本阶段没有新增数据库表，使用前面已经建好的关系表：

- `molecules`
- `molecule_properties`

### 3.2 molecules 状态变化

候选分子从 `seed_ligands` 导入后，初始状态通常为：

```text
status = imported_from_seed
labels = ["seed_ligand", "needs_structure_validation"]
```

执行轻量校验后：

通过轻量校验：

```text
status = structure_validated
labels += ["light_validation_passed", "needs_rdkit_validation"]
```

未通过轻量校验：

```text
status = invalid_structure
labels += ["invalid_smiles", "<具体失败原因>"]
```

当前可能出现的失败原因标签：

- `unbalanced_parentheses`：圆括号不成对。
- `unbalanced_brackets`：方括号不成对。
- `unpaired_ring_digit`：环编号不成对。
- `unsupported_atom_tokens`：没有识别出当前轻量规则支持的重原子。
- `invalid_smiles`：基础字符集或空值校验失败。

### 3.3 molecule_properties 写入

通过轻量校验的分子会写入或更新 `molecule_properties`：

| 字段 | 当前来源 |
|---|---|
| `molecule_id` | 对应 `molecules.molecule_id` |
| `mw` | 按 SMILES 中识别出的元素粗略估算 |
| `hbd` | 当前按 N/O 数量粗略估算 |
| `hba` | 当前按 N/O/S/F/Cl/Br/I 数量粗略估算 |
| `logp` | 暂未计算，保留为 `null` |
| `tpsa` | 暂未计算，保留为 `null` |
| `sa_score` | 暂未计算，保留为 `null` |
| `tool_metadata` | 记录校验器、重原子数、元素计数、运行次数 |

示例 `tool_metadata`：

```json
{
  "validator": "lightweight_smiles_validator",
  "heavy_atom_count": 3,
  "element_counts": {
    "C": 2,
    "O": 1
  },
  "validation_run_count": 1
}
```

重复执行校验时，不会新增第二条 `molecule_properties`，而是更新同一条记录，并让 `validation_run_count` 加 1。

## 4. 轻量校验规则

当前校验入口：

```python
validate_smiles_lightweight(smiles)
```

校验步骤：

1. 复用导入阶段的字符级 SMILES 检查：
   - 非空。
   - 不包含空白字符。
   - 不包含 `_`。
   - 至少包含一个字母。
   - 只允许当前白名单字符。
2. 检查圆括号是否配对。
3. 检查方括号是否配对。
4. 检查环编号是否成对：
   - 支持普通单数字环编号，例如 `c1ccccc1`。
   - 支持 `%12` 形式的两位环编号计数。
5. 尝试从 SMILES 字符串里识别常见元素：
   - `B`、`C`、`N`、`O`、`F`、`P`、`S`、`Cl`、`Br`、`I`
   - 芳香小写 `c`、`n`、`o`、`s`、`p`

当前示例：

| SMILES | 结果 | 原因 |
|---|---|---|
| `CCO` | 通过 | 字符、括号、环编号都通过 |
| `c1ccccc1` | 通过 | 环编号 `1` 成对 |
| `C1CC` | 不通过 | 环编号 `1` 未闭合 |
| `C(C` | 不通过 | 圆括号未闭合 |
| `XYZ` | 不通过 | 没有识别出支持的重原子 |

## 5. 新增 API

### 5.1 批量轻量校验候选分子

```http
POST /projects/{project_id}/molecules/validate
```

用途：

- 找到项目下所有 `molecules`。
- 执行轻量 SMILES 校验。
- 更新分子状态和标签。
- 为通过校验的分子写入或更新 `molecule_properties`。

返回示例：

```json
{
  "validated_count": 1,
  "invalid_count": 2,
  "property_count": 1,
  "validated_molecule_ids": ["MOL-..."],
  "invalid_molecule_ids": ["MOL-...", "MOL-..."]
}
```

### 5.2 查询单个分子性质

```http
GET /projects/{project_id}/molecules/{molecule_id}/properties
```

用途：

- 查询已通过轻量校验并写入的性质记录。
- 如果分子不存在，返回 404。
- 如果分子存在但还没有性质记录，返回 404，并提示先运行轻量校验。

返回示例：

```json
{
  "molecule_id": "MOL-...",
  "mw": 40.021,
  "logp": null,
  "tpsa": null,
  "hbd": 1,
  "hba": 1,
  "sa_score": null,
  "tool_metadata": {
    "validator": "lightweight_smiles_validator",
    "heavy_atom_count": 3,
    "element_counts": {
      "C": 2,
      "O": 1
    },
    "validation_run_count": 1
  }
}
```

## 6. 推荐调用顺序

从一个新项目开始，推荐这样调用：

```text
POST /projects
POST /projects/{project_id}/files
POST /projects/{project_id}/ingest
GET  /projects/{project_id}/seed-ligands
POST /projects/{project_id}/molecules/import-seeds
GET  /projects/{project_id}/molecules
POST /projects/{project_id}/molecules/validate
GET  /projects/{project_id}/molecules
GET  /projects/{project_id}/molecules/{molecule_id}/properties
```

## 7. 测试覆盖

新增测试文件：

```text
tests/test_molecule_validation.py
```

覆盖内容：

- 上传包含合法和异常 SMILES 的 `.smi` 文件。
- 解析文件并导入候选分子。
- 执行批量轻量校验。
- 验证通过数量、异常数量和性质记录数量。
- 验证 `CCO` 状态变为 `structure_validated`。
- 验证 `C1CC`、`C(C` 状态变为 `invalid_structure`。
- 验证 `molecule_properties` 已写入。
- 验证重复执行校验时保持幂等。

## 8. 当前限制

本阶段有意保持轻量，存在以下限制：

- 不能判断 SMILES 是否能被真实化学 toolkit 解析。
- 不能识别价态错误、芳香性错误、盐形式、同位素、立体化学完整性等问题。
- 分子量是字符串元素计数的粗略估算，不包含隐式氢。
- HBD/HBA 是非常粗略的启发式估算。
- `logp`、`tpsa`、`sa_score` 暂不计算。

这些限制已经通过 `needs_rdkit_validation` 标签显式保留，避免后续误把当前结果当作最终化学计算结果。

## 9. 后续迁移建议

后续接入 RDKit 或 Datamol 时，建议保留现有 API，不改变前端和上层 Agent 调用方式，只替换服务内部实现：

```text
validate_project_molecules()
  -> RDKit MolFromSmiles
  -> 分子标准化
  -> 去盐/中和/互变异构处理
  -> canonical SMILES / InChIKey
  -> Descriptors.MolWt / MolLogP / TPSA / HBD / HBA
  -> PAINS / Brenk / reactive groups
  -> 更新 molecules + molecule_properties
```

这样迁移时，上层调用仍然是：

```http
POST /projects/{project_id}/molecules/validate
GET /projects/{project_id}/molecules/{molecule_id}/properties
```

## 10. 与 RAG 的关系

本阶段不开发 RAG，不下载文献向量库，也不写入向量表。

当前只使用关系数据库中的结构化表：

- `projects`
- `uploaded_files`
- `seed_ligands`
- `molecules`
- `molecule_properties`

后续 RAG 接入后，可以把文献证据、靶点信息和 assay 背景写入向量库或证据表，但不影响本阶段分子校验接口。
