# AutoGrow4适配器开发文档

初始日期：2026-07-09；工具链加固：2026-07-16

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
- 使用docking score引导分子进化
- 自动检测AutoGrow4可用性（本地/Docker）
- 使用上游正式的 `-j config.json` 入口，不把配置字段误当成独立 CLI 参数
- 当前只声明支持遗传算法模式；MCTS 不属于本适配器已经实现的能力
- 只有成功退出、生成分子且解析到 ranked fitness/docking 数值时才向上层报告成功

## 2. AutoGrow4 vs RDKit代理

| 特性 | RDKit代理 | AutoGrow4 |
|------|----------|-----------|
| 方法 | 库枚举 | 遗传算法 |
| Docking引导 | 无 | 有 |
| 优化能力 | 无 | 多代进化 |
| 速度 | 快 | 较慢 |
| 依赖 | RDKit | AutoGrow4 + Vina + Open Babel + RDKit |

## 3. 新增文件与修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/medagent/services/autogrow4_adapter.py` | 新增 | AutoGrow4适配器 |
| `src/medagent/services/molecule_generation.py` | 修改 | 集成autogrow4_adapter |
| `docker/autogrow4/Dockerfile` | 新增 | AutoGrow4 Docker镜像 |
| `docker-compose.yml` | 修改 | 添加autogrow4服务 |
| `docs/AUTOGROW4_ADAPTER_BUILD.md` | 新增 | 本文档 |

## 4. 优化模式

当前适配器只支持 AutoGrow4 的遗传算法流程。请求中的 `optimization_mode` 必须为 `genetic`；其他值会显式失败并触发既有 surrogate 回退，避免把未实现的模式标记为已经运行。

## 5. 输入输出

### 5.1 输入
- 种子SMILES文件
- 蛋白受体PDB文件
- docking grid center 和 size
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
