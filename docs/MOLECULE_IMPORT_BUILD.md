# 本次开发文档：种子配体导入候选分子

日期：2026-07-07

范围：把文件解析得到的 `seed_ligands` 导入正式 `molecules` 表，建立后续规则过滤、性质计算、Docking、ADMET 的分子入口。RAG、RDKit、Docking、ADMET 暂不接入。

## 1. 本次完成内容

本次开发补齐了从“上传文件解析”到“候选分子表”的第一段链路：

```text
uploaded_files
  -> seed_ligands
  -> molecules
```

具体完成：

- 新增种子配体导入服务：`src/medagent/services/molecule_import.py`
- 新增 API：`POST /projects/{project_id}/molecules/import-seeds`
- 新增 API：`GET /projects/{project_id}/molecules/{molecule_id}`
- 扩展 `GET /projects/{project_id}/molecules` 返回 `source_agent`
- 支持轻量 SMILES 校验
- 支持同项目内 SMILES 去重
- 支持同批次重复 seed ligand 跳过
- 支持导入摘要返回
- 中文 `/docs` 页面补充了导入入口
- 新增测试：`tests/test_molecule_import.py`

## 2. 本次明确未做

- 未接入 RDKit。
- 未做真实化学标准化。
- 未计算分子性质。
- 未写入 `molecule_properties`。
- 未生成 InChIKey。
- 未提取 scaffold。
- 未做 PAINS/Brenk/Lipinski 过滤。
- 未做候选分子生成。

当前校验只是轻量字符串校验，目的是先建立数据流，不把重化学依赖提前引进来。

## 3. 新增 API

### 3.1 导入种子配体为候选分子

```http
POST /projects/{project_id}/molecules/import-seeds
```

作用：

- 读取当前项目的 `seed_ligands`
- 对 SMILES 做轻量校验
- 按项目内已有 `molecules.smiles` 去重
- 同一批次内重复 SMILES 只导入一次
- 写入 `molecules`

返回示例：

```json
{
  "imported_count": 2,
  "duplicate_count": 1,
  "invalid_count": 1,
  "imported_molecule_ids": ["MOL-AAAA", "MOL-BBBB"],
  "skipped": [
    {
      "ligand_id": "LIG-XXXX",
      "reason": "duplicate_smiles",
      "smiles": "CCO"
    }
  ]
}
```

### 3.2 查看候选分子列表

```http
GET /projects/{project_id}/molecules
```

返回字段：

| 字段 | 说明 |
|---|---|
| `molecule_id` | 分子编号 |
| `smiles` | 当前轻量标准化后的 SMILES |
| `scaffold` | 骨架，当前为空 |
| `status` | 当前状态 |
| `labels` | 分子标签 |
| `source_agent` | 来源，当前为 `seed_ligand_import` |

### 3.3 查看单个候选分子

```http
GET /projects/{project_id}/molecules/{molecule_id}
```

用于后续前端点开单个分子卡片。

## 4. 写入 molecules 的规则

从 seed ligand 导入 molecule 时写入：

| 字段 | 值 |
|---|---|
| `molecule_id` | `MOL-` 前缀自动生成 |
| `project_id` | 当前项目 |
| `smiles` | 去首尾空白后的 SMILES |
| `inchi_key` | 当前为空 |
| `scaffold` | 当前为空 |
| `source_agent` | `seed_ligand_import` |
| `status` | `imported_from_seed` |
| `labels` | `["seed_ligand", "needs_structure_validation"]` |

## 5. 轻量 SMILES 校验

当前只做最基础的字符串校验：

- 不能为空。
- 不能包含空白字符。
- 不能包含 `_`。
- 只能包含常见 SMILES 字符：

```text
A-Z a-z 0-9 @ + - [ ] ( ) = # $ \ / % . :
```

- 至少包含一个英文字母。

会被跳过的例子：

```text
not_a_smiles
???
空字符串
含空格的字符串
```

注意：这个校验不是化学合法性校验。下一阶段接 RDKit 后，才会真正判断价态、芳香性、环闭合、立体化学等问题。

## 6. 去重规则

去重范围：

- 当前项目已有 `molecules.smiles`
- 当前导入批次内已经导入的 SMILES

命中重复时不会再写入 `molecules`，但会在返回结果的 `skipped` 中记录：

```json
{
  "reason": "duplicate_smiles"
}
```

## 7. 推荐使用流程

完整流程：

```text
POST /projects
  -> POST /projects/{project_id}/files
  -> POST /projects/{project_id}/ingest
  -> GET /projects/{project_id}/seed-ligands
  -> POST /projects/{project_id}/molecules/import-seeds
  -> GET /projects/{project_id}/molecules
```

## 8. 测试覆盖

新增测试：

```text
tests/test_molecule_import.py
```

覆盖：

- seed ligands 能导入 molecules。
- 重复 SMILES 不重复写入。
- 明显非法 SMILES 会跳过。
- 第二次导入保持幂等，不重复创建 molecules。
- 单个 molecule 可查询。

运行：

```powershell
python -m pytest tests/test_molecule_import.py
python -m pytest
```

当前通过：

```text
2 passed in test_molecule_import.py
```

## 9. 下一步建议

下一步建议做“RDKit/Datamol 轻量接入”：

- 真正解析 SMILES。
- 标准化 canonical SMILES。
- 生成 InChIKey。
- 去盐、去同位素或保留策略。
- 计算 MW、LogP、TPSA、HBD、HBA。
- 写入 `molecule_properties`。
- 把无法解析的分子标记为 `invalid_structure`。

这样完成后，才适合进入 PAINS/Brenk 过滤和后续 Docking/ADMET。
