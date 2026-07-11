# DiffDock适配器开发文档

日期：2026-07-09

范围：在现有GNINA/Vina适配器基础上，补充DiffDock扩散模型对接能力，支持无需预定义结合口袋的分子对接。

## 1. 本阶段目标

当前Docking工具链：

```text
GNINA ✅ → CNN重打分 + 传统对接
Vina ✅ → 传统网格搜索对接
DiffDock ❌ → 扩散模型pose预测（本阶段新增）
```

本阶段补充DiffDock适配器：

```text
分子 + 蛋白 → DiffDock扩散模型 → binding pose + confidence score
```

实现后，系统可以：

- 使用DiffDock进行基于扩散模型的分子对接
- 自动检测DiffDock可用性（本地Python包/Docker）
- 当GNINA/Vina不可用时，使用DiffDock作为替代
- 解析DiffDock输出的confidence score和pose文件

## 2. DiffDock vs 传统对接

| 特性 | GNINA/Vina | DiffDock |
|------|-----------|----------|
| 方法 | 传统搜索+打分 | 扩散生成模型 |
| 结合口袋 | 需要预定义网格 | 自动预测 |
| 输出 | vina_score (kcal/mol) | confidence_score (0-1) |
| 速度 | 快 | 较慢 |
| 准确性 | 依赖口袋定义 | 更灵活 |
| GPU需求 | 可选 | 推荐 |

## 3. 新增文件与修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/medagent/services/docking_adapters.py` | 修改 | 添加DiffDock适配器函数 |
| `src/medagent/services/candidate_assessment.py` | 修改 | 更新DiffDock状态检测 |
| `docker/diffdock/Dockerfile` | 新增 | DiffDock Docker镜像 |
| `docker-compose.yml` | 修改 | 添加diffdock服务 |
| `docs/DIFFDOCK_ADAPTER_BUILD.md` | 新增 | 本文档 |

## 4. 执行模式

### 4.1 本地Python包

```bash
# 安装
pip install diffdock

# 检测方式
python -c "import diffdock"
```

### 4.2 Docker容器

```bash
# 构建
docker compose build diffdock

# 运行
docker run --rm \
    -v ./data:/data \
    diffdock:latest \
    python -m diffdock \
    --protein_path /data/protein.pdb \
    --ligand_path /data/ligand.sdf \
    --output_dir /data/output
```

## 5. 输入输出格式

### 5.1 输入

```json
{
  "receptor_file": "protein.pdb",
  "ligand_file": "ligand.sdf",
  "output_dir": "./output",
  "molecule_id": "MOL-001"
}
```

### 5.2 输出

DiffDock输出：
- `confidence_score`: 0-1，越高越可信
- `rank1.sdf`: 最佳binding pose
- `rank2.sdf`: 次佳pose（可选）

转换为项目格式：
- `vina_score`: 由confidence_score转换（可选）
- `cnn_score`: 使用confidence_score
- `pose_file`: SDF文件路径

## 6. Confidence Score映射

DiffDock的confidence score (0-1) 可以映射到传统对接分数：

```python
# 粗略映射（可选）
vina_score = -10 * confidence_score  # 0.8 → -8.0 kcal/mol
```

或直接使用confidence score作为质量指标。

## 7. 标签系统

| 标签 | 含义 |
|------|------|
| `diffdock_adapter` | 使用DiffDock |
| `diffdock_external_docking` | 本地DiffDock |
| `diffdock_docker_docking` | Docker DiffDock |
| `external_docking_adapter_used` | 成功使用外部工具 |
| `external_docking_adapter_failed` | 外部工具失败 |

## 8. 测试策略

由于DiffDock需要较大的模型文件，测试使用monkeypatch模拟：

```python
def test_diffdock_parsing():
    # 测试输出解析
    stdout = "confidence_score: 0.85"
    result = parse_diffdock_output(stdout, output_dir, "MOL-1")
    assert result["confidence_score"] == 0.85
```

## 9. 后续改进

1. 支持DiffDock的多个rank输出
2. 添加pocket-guided模式
3. 优化Docker镜像大小
4. 添加GPU支持检测
5. 批量对接优化
