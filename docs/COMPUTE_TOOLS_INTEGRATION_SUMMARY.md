# 计算化学工具接入总结

日期：2026-07-09

## 已完成的工具接入

### 1. ADMET预测 - Chemprop适配器 ✅

| 文件 | 操作 |
|------|------|
| `src/medagent/services/admet_adapter.py` | 新增 |
| `src/medagent/services/candidate_assessment.py` | 修改 |
| `docker/chemprop/Dockerfile` | 新增 |
| `docker-compose.yml` | 修改 |
| `tests/test_admet_adapter.py` | 新增 |
| `docs/CHEMPROP_ADAPTER_BUILD.md` | 新增 |

支持的预测项：
- hERG心脏毒性
- Ames致突变性
- CYP3A4/CYP2D6抑制
- 溶解度
- 渗透性
- DILI肝毒性
- Pgp底物
- BBB穿透

### 2. 分子对接 - DiffDock适配器 ✅

| 文件 | 操作 |
|------|------|
| `src/medagent/services/docking_adapters.py` | 修改 |
| `docker/diffdock/Dockerfile` | 新增 |
| `docs/DIFFDOCK_ADAPTER_BUILD.md` | 新增 |

特点：
- 基于扩散模型的分子对接
- 无需预定义结合口袋
- 输出confidence score

### 3. 分子生成 - REINVENT4适配器 ✅

| 文件 | 操作 |
|------|------|
| `src/medagent/services/reinvent4_adapter.py` | 新增 |
| `src/medagent/services/molecule_generation.py` | 修改 |
| `docker/reinvent4/Dockerfile` | 新增 |
| `docs/REINVENT4_ADAPTER_BUILD.md` | 新增 |

特点：
- 强化学习式分子优化
- 支持多种打分策略
- TOML配置文件

### 4. 分子生成 - AutoGrow4适配器 ✅

| 文件 | 操作 |
|------|------|
| `src/medagent/services/autogrow4_adapter.py` | 新增 |
| `src/medagent/services/molecule_generation.py` | 修改 |
| `docker/autogrow4/Dockerfile` | 新增 |
| `docs/AUTOGROW4_ADAPTER_BUILD.md` | 新增 |

特点：
- 遗传算法式分子优化
- 支持docking引导
- MCTS和遗传两种模式

## 部署方式

所有工具都支持两种部署方式：

### 1. 本地安装（推荐开发环境）
```bash
pip install chemprop
pip install reinvent4
pip install autogrow4
```

### 2. Docker容器（推荐生产环境）
```bash
docker compose build chemprop reinvent4 autogrow4 diffdock
docker compose up -d chemprop  # 按需启动
```

## 工具检测机制

每个适配器都有自动检测功能：

```python
# 检测顺序
1. Python包导入
2. CLI命令检测
3. Docker镜像检测
4. 回退到RDKit代理
```

## 代理回退机制

当真实工具不可用时，系统会：

1. 使用RDKit描述符进行代理估算
2. 在结果中标记 `rdkit_surrogate_*` 标签
3. 在warnings中提示工具未安装
4. 保证系统始终可用

## 测试验证

运行测试：
```bash
python -m pytest tests/test_admet_adapter.py -v
python -m pytest tests/test_docking_adapters.py -v
python -m pytest tests/test_molecule_generation.py -v
```

## 下一步

1. 安装Docker Desktop
2. 构建工具镜像：`docker compose build chemprop reinvent4 autogrow4 diffdock`
3. 运行端到端测试
4. 监控工具运行状态
