# 服务器环境配置指南

## 项目环境需求总览

这是一个小分子药物设计 Agent 系统，需要以下环境：

### 核心依赖
- **Python 3.11+** （必须）
- **Docker + Docker Compose**（必须，用于 PostgreSQL、MinIO 和计算工具）
- **Node.js 18+** + **pnpm**（前端需要，如果只部署后端可选）
- **NVIDIA GPU + CUDA**（可选，用于深度学习工具如 GNINA、Chemprop、DiffDock 等）

### 化学计算工具（Docker 镜像）
- **GNINA**：分子对接（需要 GPU）
- **AutoDock Vina**：分子对接备选
- **Chemprop**：ADMET 预测（需要 GPU）
- **DiffDock**：姿态预测（需要 GPU）
- **REINVENT4**：分子生成（需要 GPU）
- **AutoGrow4**：分子生成
- **AiZynthFinder**：逆合成路线规划（需要 GPU）

## 服务器配置步骤

### 第一步：连接服务器并检查 sudo 权限

```bash
ssh -p 52048 MolAgent@10.3.95.48
# 或通过跳板机：
# ssh -J tunnel-user@101.132.173.78:10022 -p 52048 MolAgent@127.0.0.1
```

连接后检查 sudo 权限：
```bash
sudo -v
# 或
sudo whoami
```

如果有 sudo 权限会提示输入密码并返回 `root`。

---

### 第二步：安装 Python 3.11+

检查当前 Python 版本：
```bash
python3 --version
```

如果版本低于 3.11，需要安装：

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev
```

**CentOS/RHEL:**
```bash
sudo yum install -y python3.11 python3.11-devel
```

设置 Python 3.11 为默认：
```bash
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
```

---

### 第三步：安装 Docker 和 Docker Compose

**安装 Docker:**
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

**启动 Docker 服务:**
```bash
sudo systemctl start docker
sudo systemctl enable docker
```

**将当前用户加入 docker 组（避免每次都用 sudo）:**
```bash
sudo usermod -aG docker $USER
newgrp docker
```

**验证 Docker 安装:**
```bash
docker --version
docker compose version
```

---

### 第四步：（可选）安装 NVIDIA Docker 支持

如果服务器有 NVIDIA GPU 并且需要使用 GPU 加速工具（GNINA、Chemprop、DiffDock 等），需要安装 NVIDIA Container Toolkit。

**检查 GPU:**
```bash
nvidia-smi
```

**安装 NVIDIA Container Toolkit:**
```bash
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo systemctl restart docker
```

**测试 GPU Docker 支持:**
```bash
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

---

### 第五步：克隆项目到服务器

```bash
cd ~
git clone https://github.com/darkred2233/small-molecule-drug-design-agent.git
cd small-molecule-drug-design-agent
```

---

### 第六步：配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件：
```bash
nano .env
# 或
vim .env
```

关键配置项：
```env
# 如果没有 DashScope API key，设置为 false 使用本地 fallback
MEDAGENT_RAG_USE_REMOTE_EMBEDDINGS=false
MEDAGENT_RAG_USE_REMOTE_RERANK=false

# 如果有 DashScope key，填入：
MEDAGENT_DASHSCOPE_API_KEY=your-api-key-here
```

---

### 第七步：启动基础服务（PostgreSQL + MinIO + API）

```bash
# 构建并启动 API、PostgreSQL 和 MinIO
docker compose up -d --build api postgres minio

# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f api
```

**检查服务是否正常:**
- API 健康检查：`curl http://localhost:8000/health`
- API 文档：在浏览器访问 `http://<服务器IP>:8000/docs`
- MinIO 控制台：`http://<服务器IP>:9001`（账号：medagent / medagent-secret）

---

### 第八步：（可选）构建化学计算工具镜像

**构建核心工具（GNINA、Vina、Chemprop）:**
```bash
# 如果是 Linux 服务器，需要先安装 PowerShell 或者手动构建
docker compose build gnina vina chemprop
```

**或者手动逐个构建:**
```bash
cd docker/vina
docker build -t vina:latest .

cd ../chemprop
docker build -t chemprop:latest .

# GNINA 使用预构建镜像
docker pull gnina/gnina:latest
```

**构建全部工具:**
```bash
docker compose build gnina vina chemprop diffdock reinvent4 autogrow4 aizynthfinder
```

**注意：** 
- 这些镜像构建可能需要很长时间（尤其是深度学习相关的）
- 如果没有 GPU，可以跳过需要 GPU 的工具，系统会自动回退到 RDKit surrogate

---

### 第九步：（可选）安装 Node.js 和 pnpm（用于前端）

如果需要在服务器上运行前端：

```bash
# 安装 Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# 启用 corepack 并安装 pnpm
sudo corepack enable
corepack prepare pnpm@latest --activate

# 验证
node --version
pnpm --version
```

**构建前端:**
```bash
cd apps/web
pnpm install
pnpm build
```

---

### 第十步：验证安装

**检查 Docker 工具状态:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev,chem,rag]"

# 检查工具
python scripts/check_tools.py --verbose --test
```

**测试 API:**
```bash
curl http://localhost:8000/health
curl http://localhost:8000/tools/status
```

---

## 常见问题

### 1. 权限不足
如果没有 sudo 权限，联系管理员或使用 Conda 环境：
```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
conda create -n medagent python=3.11
conda activate medagent
```

### 2. Docker 权限问题
确保用户在 docker 组：
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### 3. GPU 不可用
如果 `nvidia-smi` 失败，检查驱动安装：
```bash
sudo ubuntu-drivers devices
sudo ubuntu-drivers autoinstall
sudo reboot
```

### 4. 端口被占用
修改 `docker-compose.yml` 中的端口映射，例如：
```yaml
ports:
  - "8080:8000"  # 改为 8080
```

### 5. 镜像拉取慢
配置 Docker 镜像加速器（如阿里云、网易云等）。

---

## 最小化部署（仅后端 API）

如果只需要跑后端 API 和基础服务，不需要计算工具：

```bash
# 1. 安装 Python 3.11+
# 2. 安装 Docker
# 3. 克隆项目
# 4. 配置 .env
# 5. 启动服务
docker compose up -d --build api postgres minio

# 6. 检查
curl http://localhost:8000/health
```

这样就能运行基础的 API 服务，计算工具会自动回退到 surrogate 模式。

---

## 生产环境建议

1. **使用 nginx 反向代理** 并配置 HTTPS
2. **配置防火墙** 只开放必要端口（80、443）
3. **使用专用数据库服务器** 而不是 Docker 容器
4. **定期备份数据库和 MinIO** 存储
5. **监控资源使用情况**（CPU、内存、GPU、磁盘）
6. **日志管理**（使用 ELK 或 Loki）

---

## 下一步

配置完成后，参考 `README.md` 中的"推荐端到端流程"开始使用系统。
