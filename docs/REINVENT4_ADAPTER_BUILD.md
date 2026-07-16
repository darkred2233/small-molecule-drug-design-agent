# REINVENT4适配器开发文档

初始日期：2026-07-09；工具链加固：2026-07-16

范围：接入REINVENT4 prior sampling，并如实区分真实采样、项目约束过滤和RDKit surrogate 回退。

## 1. 本阶段目标

当前REINVENT4使用RDKit代理：

```text
种子分子 → RDKit库枚举 → Tanimoto打分 → 候选分子
```

当前接入的真实REINVENT4链路：

```text
prior模型 → REINVENT4 sampling → SMILES/性质/相似度复核 → 候选分子
```

实现后，系统可以：

- 使用配置的非空 prior 文件执行真实REINVENT4 sampling
- 记录命令、prior路径与大小、设备、超时和Docker镜像
- prior sampling没有项目目标函数分数；缺失值保存为`null`，不伪造`0.0`
- 明确标记当前结果不是靶点导向强化学习或多目标优化
- 自动检测REINVENT4可用性（本地/Docker）
- 当REINVENT4不可用、执行失败或真实输出不满足项目约束时回退到RDKit/Datamol代理

## 2. REINVENT4 vs RDKit代理

| 特性 | RDKit代理 | REINVENT4 |
|------|----------|-----------|
| 方法 | 库枚举 | prior sampling |
| 多样性 | 受限于预定义库 | 高多样性 |
| 靶点优化 | 无 | 当前未实现 |
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

## 4. 当前模式边界

`scoring_strategy` 字段为后续RL/打分配置保留。当前 sampling 配置不会应用 `simple`、`multi_parameter` 或 `scaffold_hop` 打分策略，也不会使用 seed SMILES 作为条件输入；请求这些能力时会写入 warning，而不会假装已经完成优化。

## 5. 配置文件格式

REINVENT4使用TOML配置文件：

```toml
run_type = "sampling"
device = "cuda:0"
json_out_config = "/data/sampling.json"

[parameters]
model_file = "/data/model.prior"
output_file = "/data/output.csv"
num_smiles = 100
unique_molecules = true
randomize_smiles = true
```

## 6. 标签系统

| 标签 | 含义 |
|------|------|
| `reinvent4_generated` | REINVENT4生成 |
| `reinvent4_local` | 本地运行 |
| `reinvent4_docker` | Docker运行 |
| `rdkit_scored_reinvent4_surrogate` | RDKit代理回退 |

## 7. 后续改进

1. 增加靶点相关打分组件和正式RL配置模板
2. 支持迁移学习
3. 保存可复现的小规模GPU运行记录
4. 批量生成优化
5. 添加生成多样性控制
