# REINVENT4适配器开发文档

日期：2026-07-09

范围：接入REINVENT4进行基于强化学习的分子生成，替代当前的RDKit库枚举代理。

## 1. 本阶段目标

当前REINVENT4使用RDKit代理：

```text
种子分子 → RDKit库枚举 → Tanimoto打分 → 候选分子
```

本阶段接入真实REINVENT4：

```text
种子分子 → REINVENT4强化学习 → 多目标优化 → 候选分子
```

实现后，系统可以：

- 使用REINVENT4进行强化学习式分子优化
- 支持多种打分策略（simple, multi_parameter, scaffold_hop）
- 自动检测REINVENT4可用性（本地/Docker）
- 当REINVENT4不可用时回退到RDKit代理

## 2. REINVENT4 vs RDKit代理

| 特性 | RDKit代理 | REINVENT4 |
|------|----------|-----------|
| 方法 | 库枚举 | 强化学习 |
| 多样性 | 受限于预定义库 | 高多样性 |
| 优化能力 | 无 | 多目标优化 |
| 速度 | 快 | 较慢 |
| GPU需求 | 无 | 推荐 |

## 3. 新增文件与修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/medagent/services/reinvent4_adapter.py` | 新增 | REINVENT4适配器 |
| `src/medagent/services/molecule_generation.py` | 修改 | 集成reinvent4_adapter |
| `docker/reinvent4/Dockerfile` | 新增 | REINVENT4 Docker镜像 |
| `docker-compose.yml` | 修改 | 添加reinvent4服务 |
| `docs/REINVENT4_ADAPTER_BUILD.md` | 新增 | 本文档 |

## 4. 打分策略

### 4.1 Simple Strategy
单目标优化，适合快速筛选。

### 4.2 Multi-Parameter Strategy
多目标优化，同时考虑：
- 类药性 (QED)
- 合成可及性 (SA Score)
- 分子量 (MW)
- LogP

### 4.3 Scaffold Hop Strategy
保留核心骨架，优化侧链。

## 5. 配置文件格式

REINVENT4使用TOML配置文件：

```toml
[run_type]
name = "sampling"

[parameters]
summary_csv_file = "output.csv"
num_smiles = 100
unique_molecules = true

[scoring]
type = "simple"
[[scoring.component]]
[scoring.component.custom_sum]
name = "custom_sum"
```

## 6. 标签系统

| 标签 | 含义 |
|------|------|
| `reinvent4_generated` | REINVENT4生成 |
| `reinvent4_local` | 本地运行 |
| `reinvent4_docker` | Docker运行 |
| `rdkit_scored_reinvent4_surrogate` | RDKit代理回退 |

## 7. 后续改进

1. 支持自定义打分函数
2. 支持迁移学习
3. 添加GPU加速
4. 批量生成优化
5. 添加生成多样性控制
