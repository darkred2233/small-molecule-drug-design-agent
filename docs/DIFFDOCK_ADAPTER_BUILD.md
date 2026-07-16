# DiffDock适配器开发文档

初始日期：2026-07-09；工具链加固：2026-07-16

范围：在现有GNINA/Vina适配器基础上，补充DiffDock扩散模型对接能力，支持无需预定义结合口袋的分子对接。

## 1. 本阶段目标

Docking工具链按运行时状态选择：

```text
有网格且GNINA可用 → GNINA
有网格、Vina可用且PDBQT输入有效 → Vina
DiffDock可用 → DiffDock（不要求网格）
外部工具失败 → 既有surrogate回退
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
- 每次运行使用独立输出目录，避免把历史pose误当成本次结果
- 只有本次pose文件和confidence同时存在时才标记成功

## 2. DiffDock vs 传统对接

| 特性 | GNINA/Vina | DiffDock |
|------|-----------|----------|
| 方法 | 传统搜索+打分 | 扩散生成模型 |
| 结合口袋 | 需要预定义网格 | 自动预测 |
| 输出 | vina_score (kcal/mol) | 模型特定、未校准的confidence score |
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
# 检测方式
python -m diffdock --help
```

### 4.2 Docker容器

项目镜像不内置模型权重。真实运行需要只读挂载两个上游模型目录：

- score目录：`model_parameters.yml`、`best_ema_inference_epoch_model.pt`
- confidence目录：`model_parameters.yml`、`best_model_epoch75.pt`

状态检查只验证这些明确文件；依赖包或镜像中的其他PyTorch权重不会被当作DiffDock模型。

```bash
# 构建
docker compose build diffdock

# 运行
docker run --rm \
    -v ./data:/data \
    --entrypoint python \
    diffdock:latest \
    /app/diffdock/inference.py \
    --protein_path /data/protein.pdb \
    --ligand_description /data/ligand.sdf \
    --out_dir /data/output
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
- `confidence_score`: 模型特定、未校准，通常越高表示模型越偏好该pose，但不能直接解释为概率
- `rank1_confidence*.sdf`: 工具排序第一的binding pose
- 其他rank pose（可选）

转换为项目格式：
- `diffdock_confidence`: 原始DiffDock confidence语义
- `vina_score`: 不由confidence伪造
- `cnn_score`: 不复用DiffDock confidence
- `pose_file`: SDF文件路径

## 6. Confidence Score语义

当前实现不会把DiffDock confidence线性映射成Vina kcal/mol，也不会写入GNINA CNN score。不同模型、checkpoint和任务之间的confidence不可直接横向比较，必须保留模型与执行provenance。

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
    pose = output_dir / "MOL-1_rank1_confidence-1.234.sdf"
    pose.write_text("pose\n$$$$\n", encoding="utf-8")
    stdout = ""
    result = parse_diffdock_output(stdout, output_dir, "MOL-1")
    assert result["confidence_score"] == -1.234
    assert result["best_pose_confirmed"] is True
```

## 9. 后续改进

1. 支持DiffDock的多个rank输出
2. 添加pocket-guided模式
3. 优化Docker镜像大小
4. 在目标GPU主机上保存可复现的真实运行记录
5. 批量对接优化
