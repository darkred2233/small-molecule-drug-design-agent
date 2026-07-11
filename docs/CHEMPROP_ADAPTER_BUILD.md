# Chemprop ADMET适配器开发文档

日期：2026-07-09

范围：接入Chemprop进行真实的ADMET预测，替代当前的RDKit描述符估算代理。

## 1. 本阶段目标

上一阶段ADMET使用RDKit描述符进行代理估算：

```text
分子 → RDKit描述符 → 经验公式估算 → ADMETResult
```

本阶段接入Chemprop进行真实预测：

```text
分子 → SMILES → Chemprop ML模型 → ADMETResult
```

实现后，系统可以：

- 使用Chemprop预训练模型预测8项ADMET性质
- 自动检测Chemprop可用性（本地/Docker）
- 当Chemprop不可用时回退到RDKit代理
- 支持批量预测提高效率

## 2. 新增文件与修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/medagent/services/admet_adapter.py` | 新增 | Chemprop适配器 |
| `src/medagent/services/candidate_assessment.py` | 修改 | 集成admet_adapter |
| `docker/chemprop/Dockerfile` | 新增 | Chemprop Docker镜像 |
| `docker-compose.yml` | 修改 | 添加chemprop服务 |
| `tests/test_admet_adapter.py` | 新增 | 适配器测试 |
| `docs/CHEMPROP_ADAPTER_BUILD.md` | 新增 | 本文档 |

## 3. 预测项目

按开发文档7.9节，支持以下预测：

| 属性 | 说明 | 输出类型 |
|------|------|---------|
| hERG | hERG心脏毒性风险 | probability + risk_label |
| Ames | Ames致突变风险 | probability + risk_label |
| CYP3A4 | CYP3A4抑制风险 | probability + risk_label |
| CYP2D6 | CYP2D6抑制风险 | probability + risk_label |
| solubility | 溶解度 | score + class |
| permeability | 渗透性 | score + class |
| DILI | 药物性肝损伤 | probability + risk_label |
| Pgp | P-gp底物 | probability + risk_label |
| BBB | 血脑屏障穿透 | probability + risk_label |

## 4. 执行模式

### 4.1 本地CLI模式

```bash
# 检测方式：chemprop --version
chemprop predict \
    --test-path input.csv \
    --preds-path output.csv \
    --checkpoint-dir models/
```

### 4.2 Python包模式

```python
# 检测方式：import chemprop
from chemprop.train import predict
```

### 4.3 Docker模式

```bash
# 检测方式：docker image inspect chemprop:latest
docker run --rm \
    -v ./data:/data \
    chemprop:latest \
    chemprop predict \
    --test-path /data/input.csv \
    --preds-path /data/output.csv
```

## 5. 风险分类阈值

| 属性 | 高风险阈值 | 中风险阈值 | 低风险阈值 |
|------|-----------|-----------|-----------|
| hERG | ≥0.7 | ≥0.4 | <0.4 |
| Ames | ≥0.7 | ≥0.4 | <0.4 |
| CYP3A4 | ≥0.7 | ≥0.4 | <0.4 |
| CYP2D6 | ≥0.7 | ≥0.4 | <0.4 |
| DILI | ≥0.7 | ≥0.4 | <0.4 |
| Pgp | ≥0.7 | ≥0.4 | <0.4 |
| BBB | ≥0.7 | ≥0.4 | <0.4 |

## 6. 数据库写入

ADMETResult表新增字段：

| 字段 | 来源 | 说明 |
|------|------|------|
| hERG_probability | Chemprop | hERG阻断概率 |
| hERG_risk | 计算 | high/medium/low_risk |
| Ames_probability | Chemprop | Ames阳性概率 |
| Ames_risk | 计算 | high/medium/low_risk |
| solubility | Chemprop | high/medium/low |
| permeability | Chemprop | high/medium/low |
| admet_risk_score | 计算 | 综合风险分数 |
| raw_output.CYP3A4_inhibition | Chemprop | CYP3A4抑制概率 |
| raw_output.CYP2D6_inhibition | Chemprop | CYP2D6抑制概率 |
| raw_output.DILI_probability | Chemprop | DILI概率 |
| raw_output.Pgp_substrate | Chemprop | Pgp底物概率 |
| raw_output.BBB_penetration | Chemprop | BBB穿透概率 |

## 7. 标签系统

| 标签 | 含义 |
|------|------|
| `chemprop_admet` | 使用Chemprop预测 |
| `chemprop_docker` | 通过Docker运行 |
| `chemprop_predicted` | 单分子预测完成 |
| `rdkit_surrogate_admet` | 回退到RDKit代理 |
| `high_risk` / `medium_risk` / `low_risk` | 风险等级 |
| `admet_blocker` | 高风险，建议淘汰 |
| `admet_warning` | 中等风险，需要关注 |
| `admet_clean` | ADMET整体较干净 |

## 8. 测试覆盖

| 测试 | 覆盖内容 |
|------|---------|
| `test_risk_label` | 风险分类阈值 |
| `test_solubility_class` | 溶解度分类 |
| `test_permeability_class` | 渗透性分类 |
| `test_writes_smiles_to_csv` | 输入CSV格式 |
| `test_parses_basic_output` | 输出解析 |
| `test_handles_missing_values` | 缺失值处理 |

## 9. 使用方式

### 9.1 安装Chemprop

```bash
# 方式1: pip安装
pip install chemprop

# 方式2: Docker
docker compose build chemprop
```

### 9.2 运行ADMET预测

```bash
# API方式
curl -X POST http://localhost:8000/projects/{project_id}/candidate-assessment/run

# CLI方式（未来支持）
python -m medagent.cli assessment run --project-id {project_id}
```

## 10. 后续改进

1. 支持自定义Chemprop模型路径
2. 支持微调模型
3. 添加更多ADMET端点
4. 优化批量预测性能
5. 添加预测置信度
