# 计算化学工具安装指南

本文档说明如何安装和配置小分子药物设计Agent所需的计算化学工具。

## 工具概览

| 工具 | 必需程度 | 用途 | 安装方式 |
|------|---------|------|---------|
| RDKit | **必需** | 分子验证、描述符计算、规则过滤 | pip / conda |
| Chemprop | 推荐 | ADMET预测 | pip / Docker |
| GNINA | 推荐 | 分子对接（带CNN评分） | 二进制 / Docker |
| AutoDock Vina | 可选 | 分子对接 | 二进制 / conda |
| DiffDock | 可选 | 基于扩散模型的对接 | git / Docker |
| REINVENT4 | 可选 | 强化学习分子生成 | pip / Docker |
| AutoGrow4 | 可选 | 遗传算法分子生成 | pip / Docker |

## 快速开始

### 方案1：最小安装（仅RDKit）

适合快速试用和开发环境：

```bash
# 使用conda（推荐）
conda install -c conda-forge rdkit

# 或使用pip
pip install rdkit
```

**说明：** 系统会对缺失的工具使用RDKit代理回退机制，保证基本功能可用。

### 方案2：完整本地安装

适合开发环境和小规模使用：

```bash
# 1. 安装RDKit
conda install -c conda-forge rdkit

# 2. 安装Chemprop
pip install chemprop

# 3. 安装AutoDock Vina（可选）
conda install -c conda-forge vina

# 4. 安装REINVENT4（可选）
pip install reinvent
```

### 方案3：Docker部署（推荐生产环境）

适合生产环境和大规模使用：

```bash
# 1. 确保安装Docker Desktop

# 2. 构建所有工具镜像
cd small-molecule-drug-design-agent
docker compose build

# 3. 启动需要的服务
docker compose up -d chemprop
docker compose up -d gnina
docker compose up -d reinvent4

# 4. 检查服务状态
docker compose ps
```

## 详细安装说明

### 1. RDKit（必需）

RDKit是开源化学信息学工具包，提供分子操作、描述符计算和结构警报检测。

**使用conda安装（推荐）：**

```bash
conda create -n medagent python=3.11
conda activate medagent
conda install -c conda-forge rdkit
```

**使用pip安装：**

```bash
pip install rdkit
```

**验证安装：**

```python
from rdkit import Chem
mol = Chem.MolFromSmiles("CCO")
print(f"RDKit版本: {Chem.rdBase.rdkitVersion}")
```

### 2. Chemprop（推荐）

Chemprop是基于消息传递神经网络的分子性质预测工具。

**使用pip安装：**

```bash
pip install chemprop
```

**使用Docker：**

```bash
# 构建镜像
docker compose build chemprop

# 启动服务
docker compose up -d chemprop

# 测试
docker compose exec chemprop chemprop --version
```

**验证安装：**

```bash
chemprop --version
```

### 3. GNINA（推荐）

GNINA是增强版AutoDock Vina，提供CNN评分功能。

**Linux安装：**

```bash
# 下载二进制文件
wget https://github.com/gnina/gnina/releases/download/v1.0.3/gnina
chmod +x gnina
sudo mv gnina /usr/local/bin/

# 验证
gnina --version
```

**使用Docker：**

```bash
# 构建镜像
docker compose build gnina

# 运行对接
docker compose run gnina gnina --version
```

**macOS/Windows：** 推荐使用Docker方式。

### 4. AutoDock Vina（可选）

经典的分子对接工具。

**使用conda安装：**

```bash
conda install -c conda-forge vina
```

**验证安装：**

```bash
vina --version
```

### 5. DiffDock（可选）

基于扩散模型的分子对接方法。

**从源码安装：**

```bash
git clone https://github.com/gcorso/DiffDock.git
cd DiffDock
pip install -e .
```

**使用Docker：**

```bash
docker compose build diffdock
```

### 6. REINVENT4（可选）

基于强化学习的分子生成工具。

**使用pip安装：**

```bash
pip install reinvent
```

**使用Docker：**

```bash
docker compose build reinvent4
```

### 7. AutoGrow4（可选）

基于遗传算法的分子生成工具。

**从源码安装：**

```bash
git clone https://github.com/durrantlab/autogrow4.git
cd autogrow4
pip install -e .
```

**使用Docker：**

```bash
docker compose build autogrow4
```

## 验证安装

运行工具检测脚本：

```bash
# 检查所有工具状态
python scripts/check_tools.py --verbose

# 运行基本功能测试
python scripts/check_tools.py --test
```

输出示例：

```
============================================================
小分子药物设计Agent - 计算工具检测
============================================================

✅ RDKit
   版本: 2023.09.1
   模式: python_package

✅ Chemprop
   版本: 1.6.1
   模式: python_package

❌ GNINA
   状态: 未安装或不可用

✅ AutoDock Vina
   版本: 1.2.3
   路径: vina

============================================================
可用工具: 3/7
============================================================
```

## Docker Compose配置

项目提供了完整的Docker Compose配置文件。

**启动所有服务：**

```bash
docker compose up -d
```

**启动特定服务：**

```bash
# 仅启动ADMET预测
docker compose up -d chemprop

# 仅启动对接服务
docker compose up -d gnina

# 仅启动分子生成
docker compose up -d reinvent4
```

**查看日志：**

```bash
docker compose logs -f chemprop
```

**停止服务：**

```bash
docker compose down
```

## 性能优化

### GPU加速

某些工具支持GPU加速（Chemprop、DiffDock）：

```bash
# 检查NVIDIA驱动
nvidia-smi

# 使用GPU版本的Docker镜像
docker compose -f docker-compose.gpu.yml up -d chemprop
```

### 并行计算

对于批量计算，可以配置并行度：

```bash
# 设置环境变量
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
```

## 常见问题

### Q: RDKit安装失败

**A:** 使用conda而不是pip：

```bash
conda install -c conda-forge rdkit
```

### Q: Chemprop预测很慢

**A:** 使用GPU版本或调整batch size：

```bash
pip install chemprop[gpu]
```

### Q: GNINA在Windows上无法运行

**A:** Windows用户推荐使用WSL2 + Docker或直接使用Docker Desktop。

### Q: 工具检测显示"不可用"但已安装

**A:** 检查PATH环境变量：

```bash
# Linux/macOS
which gnina
echo $PATH

# Windows
where vina
echo %PATH%
```

## 系统要求

### 最小配置

- CPU: 4核心
- 内存: 8 GB
- 硬盘: 20 GB
- Python: 3.10+

### 推荐配置

- CPU: 8核心+
- 内存: 16 GB+
- 硬盘: 100 GB+ (SSD)
- GPU: NVIDIA GPU (8GB+ VRAM)
- Python: 3.11

## 许可证说明

请注意各工具的许可证要求：

- **RDKit**: BSD许可证（商业友好）
- **Chemprop**: MIT许可证（商业友好）
- **GNINA**: Apache 2.0许可证（商业友好）
- **AutoDock Vina**: Apache 2.0许可证（商业友好）
- **DiffDock**: MIT许可证（商业友好）
- **REINVENT4**: Apache 2.0许可证（商业友好）
- **AutoGrow4**: GPL v3（注意商业使用限制）

## 技术支持

如遇到安装问题：

1. 查看工具官方文档
2. 检查GitHub Issues
3. 运行 `python scripts/check_tools.py --verbose` 获取详细错误信息

## 更新工具

定期更新工具以获得最新功能和bug修复：

```bash
# 更新pip包
pip install --upgrade rdkit chemprop reinvent

# 更新conda包
conda update rdkit vina

# 重新构建Docker镜像
docker compose build --no-cache
```

## 下一步

安装完成后：

1. 运行测试：`python -m pytest tests/`
2. 启动API服务器：`uvicorn medagent.api.app:create_app --factory`
3. 访问Swagger文档：`http://127.0.0.1:8000/swagger`
4. 查看开发文档：`docs/`
