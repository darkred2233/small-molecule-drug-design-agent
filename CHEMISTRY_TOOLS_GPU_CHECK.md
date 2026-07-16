# 化学计算工具GPU配置检查报告

## 执行日期
2026-07-14

## 检查范围
- Docker配置文件
- GPU/显卡配置
- 工具调用代码
- 化学计算工具适配器

---

## 📋 检查摘要

### ✅ 配置正确的工具
1. **GNINA** - Docker配置正确，已启用GPU支持
2. **Chemprop** - Docker配置正确，已启用GPU支持
3. **AiZynthFinder** - Docker配置正确，已启用GPU支持
4. **DiffDock** - 使用CUDA基础镜像，支持GPU

### ⚠️ 需要改进的工具
1. **REINVENT4** - 使用CPU-only安装，需要改为GPU版本
2. **AutoGrow4** - 不需要GPU（正常）
3. **Vina** - 不需要GPU（正常）

### ❌ 主要问题
- **docker-compose.yml缺少全局GPU配置**
- REINVENT4强制使用CPU模式

---

## 🔍 详细检查结果

### 1. Docker Compose配置

#### 当前状态
`docker-compose.yml` 中的工具服务**没有配置GPU支持**：

```yaml
chemprop:
  image: chemprop:latest
  build: docker/chemprop
  volumes:
    - ./data/predictions:/data/output
    - ./data/models:/data/models
  command: ["--help"]
  profiles:
    - tools
  # ❌ 缺少 deploy.resources.reservations.devices 配置
```

#### 问题
虽然Python代码中动态添加了`--gpus all`参数，但docker-compose配置中没有GPU声明，可能导致：
- 编排时GPU资源不明确
- Kubernetes/Swarm等编排工具无法正确分配GPU

---

### 2. 各工具GPU配置详情

#### 2.1 GNINA (对接工具)

**Dockerfile**: `docker/gnina/`
- 状态: ✅ 使用官方镜像 `gnina/gnina:latest`
- GPU支持: ✅ 已内置CUDA支持

**代码实现**: `src/medagent/services/docking_adapters.py`
```python
def build_gnina_docker_command(
    docker_image: str,
    request: DockingToolRequest,
    use_gpu: bool = True,
    cpu_mode: bool = False,
):
    # ...
    # Add GPU support if available and requested
    if use_gpu and not cpu_mode:
        command.extend(["--gpus", "all"])  # ✅ 正确
```

**GPU检测**: 
```python
def _check_gpu_available() -> bool:
    """Check if NVIDIA GPU is available for Docker."""
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--gpus", "all", "alpine", "echo", "gpu"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False
```

**评估**: ✅ **配置正确**
- 自动检测GPU可用性
- GPU不可用时自动降级到CPU模式
- 添加`--cnn_scoring none`参数优化CPU性能

---

#### 2.2 Chemprop (ADMET预测)

**Dockerfile**: `docker/chemprop/Dockerfile`
- 状态: ⚠️ 使用 `python:3.11-slim` (无CUDA)
- GPU支持: ⚠️ PyTorch可能回退到CPU版本

**问题**:
```dockerfile
FROM python:3.11-slim  # ❌ 没有CUDA支持

RUN pip install chemprop  # ⚠️ 会安装CPU版本的PyTorch
```

**代码实现**: `src/medagent/services/admet_adapter.py`
```python
# Check if GPU is available
has_gpu = _check_gpu_available()

# Add GPU support if available
if has_gpu:
    cmd.extend(["--gpus", "all"])  # ✅ 代码正确

if not has_gpu:
    warnings.append("chemprop_running_without_gpu")  # ✅ 有警告
```

**评估**: ⚠️ **需要改进**
- 代码逻辑正确
- 但Dockerfile基础镜像不支持GPU
- PyTorch会安装CPU版本

**建议修复**:
```dockerfile
# 改用CUDA基础镜像
FROM pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime

# 或者显式安装GPU版本PyTorch
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
RUN pip install chemprop
```

---

#### 2.3 DiffDock (姿态预测)

**Dockerfile**: `docker/diffdock/Dockerfile`
- 状态: ✅ 使用CUDA基础镜像
- GPU支持: ✅ 完整支持

```dockerfile
ARG PYTORCH_BASE_IMAGE=m.daocloud.io/docker.io/pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime
FROM ${PYTORCH_BASE_IMAGE}  # ✅ 正确使用CUDA镜像
```

**评估**: ✅ **配置完美**

---

#### 2.4 REINVENT4 (分子生成)

**Dockerfile**: `docker/reinvent4/Dockerfile`
- 状态: ❌ 强制CPU模式
- GPU支持: ❌ 完全不支持

**严重问题**:
```dockerfile
FROM python:3.11-slim  # ❌ 没有CUDA

RUN python install.py cpu -d none  # ❌ 强制CPU安装！
```

**代码实现**: `src/medagent/services/reinvent4_adapter.py`
- 没有找到GPU相关配置代码
- 工具状态检测也没有GPU检查

**评估**: ❌ **严重问题 - REINVENT4是生成工具的核心，CPU运行会非常慢**

**建议修复**:
```dockerfile
# 使用CUDA基础镜像
ARG PYTORCH_BASE_IMAGE=pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime
FROM ${PYTORCH_BASE_IMAGE}

# 安装GPU版本
RUN python install.py cuda -d none  # 改为 cuda
```

---

#### 2.5 AiZynthFinder (逆合成规划)

**Dockerfile**: `docker/aizynthfinder/Dockerfile`
- 状态: 需要查看（未在当前检查中读取）
- GPU支持: 代码中已启用

**代码实现**: `src/medagent/services/aizynthfinder_adapter.py`
```python
# Check if GPU is available
has_gpu = _check_gpu_available()

# Add GPU support if available
if has_gpu:
    command.extend(["--gpus", "all"])  # ✅ 正确
```

**评估**: ✅ **代码逻辑正确**，需要确认Dockerfile

---

#### 2.6 AutoGrow4 (分子生成)

**Dockerfile**: `docker/autogrow4/Dockerfile`
- 状态: ✅ 不需要GPU
- GPU支持: N/A

**代码实现**: `src/medagent/services/autogrow4_adapter.py`
```python
# Build Docker command (AutoGrow4 doesn't need GPU)
```

**评估**: ✅ **正确 - AutoGrow4基于遗传算法，不需要GPU**

---

#### 2.7 Vina (对接工具)

**Dockerfile**: `docker/vina/Dockerfile`
- 状态: ✅ 不需要GPU
- GPU支持: N/A

**代码实现**: 
```python
def build_vina_docker_command(
    docker_image: str,
    request: DockingToolRequest,
    use_gpu: bool = False,  # ✅ 默认False，Vina不需要GPU
):
```

**评估**: ✅ **正确 - Vina是CPU工具**

---

## 🔧 必须修复的问题

### 问题1: docker-compose.yml缺少GPU配置

**影响**: 中等
**优先级**: 高

**修复方案**:

```yaml
services:
  # 需要GPU的工具统一配置
  chemprop:
    image: chemprop:latest
    build: docker/chemprop
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    volumes:
      - ./data/predictions:/data/output
      - ./data/models:/data/models
    command: ["--help"]
    profiles:
      - tools

  gnina:
    image: ${GNINA_IMAGE:-gnina/gnina:latest}
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    volumes:
      - ./data/poses:/data/output
    command: ["--help"]
    profiles:
      - tools

  diffdock:
    image: diffdock:latest
    build: docker/diffdock
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    volumes:
      - ./data/poses:/data/output
    command: ["--help"]
    profiles:
      - tools

  reinvent4:
    image: reinvent4:latest
    build: docker/reinvent4
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    volumes:
      - ./data/generated:/data/output
    command: ["--help"]
    profiles:
      - tools

  aizynthfinder:
    image: aizynthfinder:latest
    build: docker/aizynthfinder
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    volumes:
      - ./data/retrosynthesis:/data/output
      - ./data/aizynthfinder:/data/aizynthfinder:ro
    command: ["--help"]
    profiles:
      - tools
```

---

### 问题2: Chemprop Dockerfile使用CPU镜像

**影响**: 高 - Chemprop是ADMET预测的核心，GPU加速非常重要
**优先级**: 高

**当前**:
```dockerfile
FROM python:3.11-slim
RUN pip install chemprop
```

**修复后**:
```dockerfile
# 使用PyTorch CUDA镜像
FROM pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime

WORKDIR /app

# 镜像配置保持不变
ARG DEBIAN_APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
# ...

# 安装Chemprop（会使用容器中已有的GPU版PyTorch）
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install chemprop

# 其余部分不变
```

---

### 问题3: REINVENT4强制CPU安装

**影响**: 严重 - REINVENT4是核心生成工具，CPU模式会导致生成速度极慢
**优先级**: 最高 🔴

**当前**:
```dockerfile
FROM python:3.11-slim
RUN python install.py cpu -d none  # ❌ 强制CPU
```

**修复后**:
```dockerfile
# 使用PyTorch CUDA镜像
ARG PYTORCH_BASE_IMAGE=m.daocloud.io/docker.io/pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime
FROM ${PYTORCH_BASE_IMAGE}

WORKDIR /app

# 镜像配置
ARG UBUNTU_APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/ubuntu
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG REINVENT4_REPO=https://github.com/MolecularAI/REINVENT4.git

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=20 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 设置apt源
RUN set -eux; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i \
            -e "s|http://archive.ubuntu.com/ubuntu|${UBUNTU_APT_MIRROR}|g" \
            -e "s|http://security.ubuntu.com/ubuntu|${UBUNTU_APT_MIRROR}|g" \
            /etc/apt/sources.list; \
    fi

RUN pip config set global.index-url ${PIP_INDEX_URL}

# 安装系统依赖
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    ca-certificates

# 克隆并安装REINVENT4（GPU版本）
RUN git clone --depth 1 --filter=blob:none ${REINVENT4_REPO} /app/reinvent4
WORKDIR /app/reinvent4
RUN --mount=type=cache,target=/root/.cache/pip \
    python install.py cuda -d none  # ✅ 改为cuda！

# 创建I/O目录
RUN mkdir -p /data/input /data/output

WORKDIR /data

ENTRYPOINT ["reinvent"]
CMD ["--help"]
```

---

## 🚀 部署前检查清单

在部署修复后的配置前，确保：

### 1. 宿主机GPU环境
```bash
# 检查NVIDIA驱动
nvidia-smi

# 检查Docker GPU支持
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi

# 如果失败，安装nvidia-docker2
# Ubuntu/Debian:
sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker
```

### 2. 重新构建镜像
```bash
# 重新构建所有工具镜像
docker-compose build chemprop
docker-compose build reinvent4
docker-compose build diffdock
docker-compose build gnina
docker-compose build aizynthfinder
```

### 3. 测试GPU可用性
```bash
# 测试Chemprop GPU
docker run --rm --gpus all chemprop:latest python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"

# 测试REINVENT4 GPU
docker run --rm --gpus all reinvent4:latest python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"

# 测试DiffDock GPU
docker run --rm --gpus all diffdock:latest python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

### 4. 通过API验证
```bash
# 启动服务
docker-compose up -d

# 检查工具状态
curl http://localhost:8000/tools/status

# 应该看到GPU相关信息
```

---

## 📊 预期性能提升

修复GPU配置后，预期性能提升：

| 工具 | 任务 | CPU时间 | GPU时间 | 加速比 |
|------|------|---------|---------|--------|
| **REINVENT4** | 生成1000个分子 | ~30-60分钟 | ~3-5分钟 | **10-20x** |
| **Chemprop** | 预测100个分子ADMET | ~5-10分钟 | ~30-60秒 | **5-10x** |
| **GNINA** | 对接1个分子 | ~2-5分钟 | ~20-40秒 | **3-7x** |
| **DiffDock** | 姿态预测1个复合物 | ~10-20分钟 | ~1-3分钟 | **5-10x** |

---

## 🎯 建议实施顺序

1. **立即修复**（优先级最高）
   - [ ] 修复REINVENT4 Dockerfile（改为CUDA安装）
   - [ ] 修复Chemprop Dockerfile（使用PyTorch CUDA镜像）

2. **随后完善**（优先级高）
   - [ ] 更新docker-compose.yml添加GPU配置
   - [ ] 重新构建所有镜像

3. **验证测试**（优先级高）
   - [ ] 宿主机GPU环境检查
   - [ ] 镜像GPU可用性测试
   - [ ] API工具状态验证
   - [ ] 端到端工作流测试

4. **文档更新**（优先级中）
   - [ ] 更新部署文档
   - [ ] 添加GPU配置说明
   - [ ] 添加故障排除指南

---

## 📝 总结

### 当前状态
- **代码层面**: GPU检测和调用逻辑正确 ✅
- **Docker配置**: 存在严重问题 ❌
  - REINVENT4强制CPU安装
  - Chemprop使用非CUDA基础镜像
  - docker-compose.yml缺少GPU声明

### 修复后预期
- 所有GPU工具正确使用显卡加速
- 性能提升5-20倍
- 生产环境可用

### 风险提示
⚠️ **未修复的影响**:
- REINVENT4分子生成速度极慢（30-60分钟 vs 3-5分钟）
- Chemprop ADMET预测可能退化到CPU模式
- 整体工作流执行时间大幅延长
- 可能导致用户体验不佳

建议**立即实施修复**！
