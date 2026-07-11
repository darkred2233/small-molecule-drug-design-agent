# 🚀 计算化学工具快速参考

## 一键检查工具状态

```bash
python scripts/check_tools.py --verbose --test
```

## Docker工具管理

```bash
# 查看所有工具状态
python scripts/manage_docker_tools.py status

# 构建Chemprop（已部署）
docker compose build chemprop

# 构建其他工具
docker compose build diffdock reinvent4 autogrow4

# 测试Chemprop完整流程
python scripts/manage_docker_tools.py test-chemprop

# 启动Chemprop服务
docker compose up -d chemprop
```

## 使用增强的RDKit

```python
from medagent.services.rdkit_enhanced import (
    validate_and_calculate_enhanced,
    calculate_drug_likeness_score,
)

# 验证分子并计算全部描述符
result = validate_and_calculate_enhanced("CC(=O)Oc1ccccc1C(=O)O")

if result.valid:
    desc = result.descriptors
    
    # 基础性质
    print(f"MW: {desc.mw}")
    print(f"LogP: {desc.logp}")
    print(f"TPSA: {desc.tpsa}")
    
    # 药物相似性
    print(f"QED: {desc.qed}")
    print(f"SA Score: {desc.sa_score}")
    print(f"Lipinski: {desc.lipinski_pass}")
    
    # 结构警报
    for alert in result.structural_alerts:
        print(f"⚠️ {alert.catalog}: {alert.description}")
    
    # 综合评分
    score = calculate_drug_likeness_score(desc)
    print(f"药物相似性: {score['overall_score']}/100")
    print(f"推荐: {score['recommendation']}")
```

## 使用工具API

```python
import requests

# 1. 检查工具状态
response = requests.get("http://localhost:8000/tools/status")
print(response.json())

# 2. RDKit验证
response = requests.post(
    "http://localhost:8000/tools/rdkit/validate",
    json={
        "smiles": "CC(=O)Oc1ccccc1C(=O)O",
        "calculate_descriptors": True,
        "check_alerts": True,
    }
)
result = response.json()
print(f"QED: {result['descriptors']['qed']}")

# 3. Chemprop ADMET预测（需要Docker服务运行）
response = requests.post(
    "http://localhost:8000/tools/admet/predict",
    json={
        "smiles_list": ["CCO", "CC(=O)Oc1ccccc1C(=O)O"],
        "molecule_ids": ["MOL-001", "MOL-002"],
        "properties": ["hERG", "Ames", "CYP3A4"],
    }
)
predictions = response.json()
```

## 运行测试

```bash
# 运行所有工具集成测试
pytest tests/test_tools_integration.py -v

# 只测试RDKit增强功能
pytest tests/test_tools_integration.py::TestRDKitEnhanced -v

# 显示详细输出
pytest tests/test_tools_integration.py -v -s
```

## 关键文件位置

| 类型 | 文件路径 |
|------|---------|
| 工具检测脚本 | `scripts/check_tools.py` |
| Docker管理脚本 | `scripts/manage_docker_tools.py` |
| RDKit增强模块 | `src/medagent/services/rdkit_enhanced.py` |
| 工具API路由 | `src/medagent/api/tools_router.py` |
| Chemprop适配器 | `src/medagent/services/admet_adapter.py` |
| 对接适配器 | `src/medagent/services/docking_adapters.py` |
| 集成测试 | `tests/test_tools_integration.py` |
| 安装指南 | `docs/TOOLS_INSTALLATION.md` |
| 工作总结 | `docs/TOOLS_COMPLETION_SUMMARY.md` |

## 下一步行动

### 立即执行（主机Windows环境）

1. **安装RDKit（必需）**
   ```bash
   pip install rdkit
   ```

2. **验证Chemprop Docker镜像**
   ```bash
   docker compose ps
   docker compose logs chemprop
   ```

3. **测试Chemprop预测**
   ```bash
   python scripts/manage_docker_tools.py test-chemprop
   ```

### 可选操作

4. **构建其他Docker工具**
   ```bash
   docker compose build diffdock
   docker compose build reinvent4
   docker compose build autogrow4
   ```

5. **集成工具API到主应用**
   编辑 `src/medagent/api/app.py`：
   ```python
   from medagent.api.tools_router import router as tools_router
   app.include_router(tools_router)
   ```

6. **访问API文档**
   ```
   http://localhost:8000/docs#/计算工具
   ```

## 故障排除

### RDKit导入失败
```bash
# 使用conda（推荐）
conda install -c conda-forge rdkit

# 或使用pip
pip install rdkit
```

### Docker镜像构建失败
```bash
# 查看详细日志
docker compose build --no-cache chemprop

# 检查Docker是否运行
docker ps
```

### Chemprop预测失败
```bash
# 检查容器日志
docker compose logs chemprop

# 重新构建镜像
docker compose build --no-cache chemprop

# 测试容器
docker compose run --rm chemprop chemprop --version
```

## 性能提示

- **批量预测**: Chemprop支持批量SMILES，建议一次提交20-100个分子
- **并行计算**: 设置 `OMP_NUM_THREADS` 环境变量控制线程数
- **GPU加速**: 如有NVIDIA GPU，使用 `docker compose -f docker-compose.gpu.yml`
- **缓存结果**: 相同SMILES的预测结果可以缓存以提高性能

## 联系和支持

- 查看详细文档: `docs/TOOLS_INSTALLATION.md`
- 查看工作总结: `docs/TOOLS_COMPLETION_SUMMARY.md`
- 运行工具检测: `python scripts/check_tools.py --verbose`
