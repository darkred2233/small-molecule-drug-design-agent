# AutoGrow4适配器开发文档

日期：2026-07-09

范围：接入AutoGrow4进行遗传算法引导的分子生成，支持docking引导的优化。

## 1. 本阶段目标

当前AutoGrow4使用RDKit代理：

```text
种子分子 → RDKit grow/link枚举 → 候选分子
```

本阶段接入真实AutoGrow4：

```text
种子分子 + 蛋白结构 → AutoGrow4遗传算法 → docking引导优化 → 候选分子
```

实现后，系统可以：

- 使用AutoGrow4进行遗传算法式分子优化
- 支持MCTS和遗传算法两种优化模式
- 使用docking score引导分子进化
- 自动检测AutoGrow4可用性（本地/Docker）

## 2. AutoGrow4 vs RDKit代理

| 特性 | RDKit代理 | AutoGrow4 |
|------|----------|-----------|
| 方法 | 库枚举 | 遗传算法 |
| Docking引导 | 无 | 有 |
| 优化能力 | 无 | 多代进化 |
| 速度 | 快 | 较慢 |
| 依赖 | RDKit | OpenBabel + RDKit |

## 3. 新增文件与修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/medagent/services/autogrow4_adapter.py` | 新增 | AutoGrow4适配器 |
| `src/medagent/services/molecule_generation.py` | 修改 | 集成autogrow4_adapter |
| `docker/autogrow4/Dockerfile` | 新增 | AutoGrow4 Docker镜像 |
| `docker-compose.yml` | 修改 | 添加autogrow4服务 |
| `docs/AUTOGROW4_ADAPTER_BUILD.md` | 新增 | 本文档 |

## 4. 优化模式

### 4.1 MCTS模式
蒙特卡洛树搜索，适合探索化学空间。

### 4.2 Genetic模式
遗传算法，适合优化已知活性分子。

## 5. 输入输出

### 5.1 输入
- 种子SMILES文件
- 蛋白受体PDB文件
- 优化参数

### 5.2 输出
- 生成的SMILES列表
- 适应度分数
- SDF结构文件

## 6. 标签系统

| 标签 | 含义 |
|------|------|
| `autogrow4_generated` | AutoGrow4生成 |
| `autogrow4_local` | 本地运行 |
| `autogrow4_docker` | Docker运行 |
| `rdkit_grow_link_autogrow4_surrogate` | RDKit代理回退 |

## 7. 后续改进

1. 支持自定义fitness函数
2. 添加并行进化
3. 支持多目标优化
4. 添加分子过滤器
5. 优化种群多样性
