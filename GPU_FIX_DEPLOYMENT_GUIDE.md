# GPU工具修复部署指南

## 📋 修复内容概述

已修复三个关键GPU配置问题：

1. ✅ **REINVENT4 Dockerfile** - 从CPU强制安装改为CUDA安装
2. ✅ **Chemprop Dockerfile** - 从python-slim改为PyTorch CUDA基础镜像  
3. ✅ **docker-compose.yml** - 为所有GPU工具添加GPU资源声明

---

## 🚀 快速部署步骤

### 步骤1: 检查宿主机GPU环境

```bash
# 1. 检查NVIDIA驱动
nvidia-smi

# 应该看到类似输出：
# +-----------------------------------------------------------------------------+
# | NVIDIA-SMI 525.xx.xx    Driver Version: 525.xx.xx    CUDA Version: 12.0   |
# +-----------------------------------------------------------------------------+

# 2. 检查Docker GPU支持
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi

# 如果报错 "unknown flag: --gpus"，需要安装nvidia-docker2
```

### 步骤2: 安装nvidia-docker2（如果需要）

**Ubuntu/Debian:**
```bash
# 添加NVIDIA Docker仓库
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# 安装nvidia-docker2
sudo apt-get update
sudo apt-get install -y nvidia-docker2

# 重启Docker服务
sudo systemctl restart docker

# 验证安装
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

**CentOS/RHEL:**
```bash
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.repo | \
  sudo tee /etc/yum.repos.d/nvidia-docker.repo

sudo yum install -y nvidia-docker2
sudo systemctl restart docker
```

### 步骤3: 重新构建Docker镜像

```bash
cd /path/to/small-molecule-drug-design-agent

# 重新构建所有GPU工具镜像
echo "重新构建REINVENT4（最重要）..."
docker-compose build reinvent4

echo "重新构建Chemprop..."
docker-compose build chemprop

echo "重新构建DiffDock..."
docker-compose build diffdock

echo "重新构建AiZynthFinder..."
docker-compose build aizynthfinder

# GNINA使用官方镜像，无需构建
# Vina和AutoGrow4不需要GPU
```

**预计构建时间:**
- REINVENT4: 10-20分钟（取决于网络速度）
- Chemprop: 5-10分钟
- DiffDock: 15-25分钟
- AiZynthFinder: 10-15分钟

### 步骤4: 测试GPU可用性

```bash
# 测试REINVENT4（最关键）
echo "测试REINVENT4 GPU支持..."
docker run --rm --gpus all reinvent4:latest python -c "import torch; print(f'PyTorch版本: {torch.__version__}'); print(f'CUDA可用: {torch.cuda.is_available()}'); print(f'CUDA版本: {torch.version.cuda}'); print(f'GPU数量: {torch.cuda.device_count()}'); print(f'GPU名称: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"

# 预期输出：
# PyTorch版本: 2.1.0+cu118
# CUDA可用: True
# CUDA版本: 11.8
# GPU数量: 1
# GPU名称: NVIDIA GeForce RTX 3090 (或你的GPU型号)

# 测试Chemprop
echo "测试Chemprop GPU支持..."
docker run --rm --gpus all chemprop:latest python -c "import torch; print(f'CUDA可用: {torch.cuda.is_available()}')"

# 测试DiffDock
echo "测试DiffDock GPU支持..."
docker run --rm --gpus all diffdock:latest python -c "import torch; print(f'CUDA可用: {torch.cuda.is_available()}')"
```

### 步骤5: 启动服务并验证

```bash
# 启动所有服务
docker-compose up -d

# 等待服务启动（约10-30秒）
sleep 15

# 检查工具状态
curl http://localhost:8000/tools/status | jq

# 预期输出应包含：
# {
#   "chemprop": {
#     "available": true,
#     "mode": "docker",
#     "docker_image": "chemprop:latest"
#   },
#   "reinvent4": {
#     "available": true,
#     "mode": "docker",
#     "docker_image": "reinvent4:latest"
#   },
#   ...
# }
```

---

## 🧪 完整功能测试

### 测试1: REINVENT4分子生成（GPU关键）

创建测试配置文件：
```bash
cat > /tmp/test_reinvent_config.json << 'EOF'
{
  "version": 3,
  "run_type": "sampling",
  "model_file": "path/to/your/model.prior",
  "output_file": "test_output.smi",
  "smiles_file": null,
  "sample_strategy": {
    "type": "multinomial",
    "sample_size": 100
  }
}
EOF
```

运行测试（需要预训练模型）：
```bash
docker run --rm --gpus all \
  -v /tmp:/data \
  reinvent4:latest \
  /data/test_reinvent_config.json
```

### 测试2: Chemprop ADMET预测

创建测试SMILES文件：
```bash
cat > /tmp/test_molecules.csv << 'EOF'
smiles
CCO
c1ccccc1
CC(C)CC1=CC=C(C=C1)C(C)C(=O)O
EOF
```

运行预测：
```bash
docker run --rm --gpus all \
  -v /tmp:/data \
  chemprop:latest \
  predict \
  --test-path /data/test_molecules.csv \
  --checkpoint-dir /data/models/checkpoint \
  --preds-path /data/predictions.csv
```

### 测试3: GNINA对接

```bash
# 需要准备受体和配体文件
docker run --rm --gpus all \
  -v /path/to/structures:/data \
  gnina/gnina:latest \
  -r /data/receptor.pdb \
  -l /data/ligand.sdf \
  -o /data/output.sdf \
  --center_x 10.0 --center_y 10.0 --center_z 10.0 \
  --size_x 20.0 --size_y 20.0 --size_z 20.0
```

---

## 🔍 故障排除

### 问题1: "unknown flag: --gpus"

**原因**: Docker没有安装nvidia-docker2  
**解决**: 按照"步骤2: 安装nvidia-docker2"操作

### 问题2: "could not select device driver"

**原因**: nvidia-docker2未正确配置  
**解决**:
```bash
sudo systemctl restart docker
# 重新测试
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

### 问题3: Docker镜像构建失败

**原因**: 网络问题或镜像源不可达  
**解决**:
```bash
# 检查网络连接
ping mirrors.tuna.tsinghua.edu.cn

# 如果网络有问题，可以临时使用代理
export http_proxy=http://your-proxy:port
export https_proxy=http://your-proxy:port

# 重新构建
docker-compose build --no-cache reinvent4
```

### 问题4: PyTorch显示CUDA不可用

**检查步骤**:
```bash
# 1. 进入容器
docker run --rm -it --gpus all reinvent4:latest bash

# 2. 在容器内检查
python -c "import torch; print(torch.cuda.is_available())"
nvidia-smi

# 3. 检查CUDA库
ls /usr/local/cuda/lib64/

# 如果CUDA不可用，可能是基础镜像问题，尝试重新构建
```

### 问题5: 工具状态API显示不可用

**检查步骤**:
```bash
# 1. 查看容器日志
docker-compose logs api

# 2. 手动测试Docker镜像
docker images | grep -E "chemprop|reinvent4|diffdock"

# 3. 测试镜像运行
docker run --rm reinvent4:latest --help

# 4. 检查API服务
curl http://localhost:8000/health
```

---

## 📊 性能基准测试

修复后，可以运行基准测试验证GPU加速效果：

### REINVENT4基准测试
```bash
# CPU模式（旧版）
time docker run --rm -v /tmp:/data reinvent4:old-cpu-version sample --num 1000

# GPU模式（新版）
time docker run --rm --gpus all -v /tmp:/data reinvent4:latest sample --num 1000

# 预期: GPU模式应该快10-20倍
```

### Chemprop基准测试
```bash
# 准备100个分子的测试集
# ...

# CPU模式
time chemprop predict --test-path test.csv --checkpoint-dir model/ --preds-path out_cpu.csv

# GPU模式  
time chemprop predict --test-path test.csv --checkpoint-dir model/ --preds-path out_gpu.csv --gpu 0

# 预期: GPU模式应该快5-10倍
```

---

## ✅ 验收清单

部署完成后，检查以下项目：

- [ ] `nvidia-smi`显示GPU信息
- [ ] `docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi`成功
- [ ] REINVENT4镜像构建成功
- [ ] Chemprop镜像构建成功
- [ ] DiffDock镜像构建成功
- [ ] REINVENT4容器内`torch.cuda.is_available()`返回`True`
- [ ] Chemprop容器内`torch.cuda.is_available()`返回`True`
- [ ] DiffDock容器内`torch.cuda.is_available()`返回`True`
- [ ] API服务`/tools/status`返回所有工具可用
- [ ] 端到端工作流测试通过

---

## 📝 回滚方案

如果修复后出现问题，可以回滚到旧版本：

```bash
# 1. 停止服务
docker-compose down

# 2. 检出旧版本Dockerfile
git checkout HEAD~1 docker/reinvent4/Dockerfile
git checkout HEAD~1 docker/chemprop/Dockerfile
git checkout HEAD~1 docker-compose.yml

# 3. 重新构建
docker-compose build

# 4. 重启服务
docker-compose up -d
```

---

## 🎯 后续优化建议

1. **监控GPU使用率**
   - 安装nvidia-dcgm或Prometheus GPU exporter
   - 监控GPU利用率、显存使用、温度等

2. **多GPU支持**
   - 如果有多张GPU，可以修改docker-compose.yml
   - 为不同工具分配不同的GPU

3. **性能调优**
   - 根据GPU型号调整batch size
   - 优化CUDA版本匹配
   - 考虑混合精度训练（FP16）

4. **定期更新**
   - 保持PyTorch和CUDA版本更新
   - 关注工具官方GPU优化建议

---

## 📞 获取帮助

遇到问题时：
1. 查看详细检查报告: `CHEMISTRY_TOOLS_GPU_CHECK.md`
2. 检查Docker日志: `docker-compose logs -f`
3. 查看API日志: `docker-compose logs -f api`
4. 检查工具状态: `curl http://localhost:8000/tools/status`

祝部署顺利！🎉
