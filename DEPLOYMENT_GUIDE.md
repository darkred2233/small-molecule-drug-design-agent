# 小分子药物设计 Agent 服务器部署指南

**服务器信息**:
- IP: 10.3.95.48 (校园网)
- 用户: MolAgent
- 密码: molagent123456

---

## 📋 部署检查清单

### 阶段 1: 环境准备
- [ ] SSH 连接成功
- [ ] 检查系统信息
- [ ] 安装 Python 3.11+
- [ ] 安装 Docker
- [ ] 安装 Docker Compose
- [ ] 配置 Docker 权限

### 阶段 2: 工具容器部署
- [ ] GNINA (对接)
- [ ] AutoDock Vina (对接)
- [ ] Chemprop (ADMET)
- [ ] PostgreSQL (数据库)
- [ ] MinIO (对象存储)

### 阶段 3: Python 环境
- [ ] 创建虚拟环境
- [ ] 安装依赖
- [ ] 配置环境变量

### 阶段 4: 验证测试
- [ ] 测试 Docker 容器
- [ ] 测试数据库连接
- [ ] 测试 Python 导入

---

## 🚀 步骤 1: 连接服务器并检查环境

### 1.1 SSH 连接
```bash
# 从你的本地计算机连接
ssh MolAgent@10.3.95.48
# 输入密码: molagent123456
```

### 1.2 检查系统信息
```bash
# 检查操作系统
cat /etc/os-release
uname -a

# 检查磁盘空间（至少需要 50GB）
df -h

# 检查内存（建议 16GB+）
free -h

# 检查 CPU
lscpu | grep "Model name"
nproc  # CPU 核心数
```

### 1.3 检查现有工具
```bash
# Python
python3 --version
which python3

# Docker
docker --version
docker compose version

# Git
git --version

# PostgreSQL 客户端
psql --version
```

---

## 🐍 步骤 2: 安装 Python 3.11

### 如果 Python 版本 < 3.11

#### Ubuntu/Debian
```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev
sudo apt install -y python3-pip

# 设置 python3.11 为默认（可选）
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
```

#### CentOS/RHEL
```bash
sudo yum install -y gcc openssl-devel bzip2-devel libffi-devel zlib-devel wget make

cd /tmp
wget https://www.python.org/ftp/python/3.11.7/Python-3.11.7.tgz
tar xzf Python-3.11.7.tgz
cd Python-3.11.7
./configure --enable-optimizations
sudo make altinstall

# 创建软链接
sudo ln -sf /usr/local/bin/python3.11 /usr/local/bin/python3
```

### 验证 Python
```bash
python3 --version  # 应该显示 3.11.x
python3 -m pip --version
```

---

## 🐳 步骤 3: 安装 Docker 和 Docker Compose

### 3.1 安装 Docker

#### Ubuntu/Debian
```bash
# 卸载旧版本
sudo apt remove docker docker-engine docker.io containerd runc

# 安装依赖
sudo apt update
sudo apt install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# 添加 Docker GPG key
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# 添加 Docker 仓库
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 安装 Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 启动 Docker
sudo systemctl start docker
sudo systemctl enable docker
```

#### CentOS/RHEL
```bash
# 卸载旧版本
sudo yum remove docker docker-client docker-client-latest docker-common \
    docker-latest docker-latest-logrotate docker-logrotate docker-engine

# 安装依赖
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# 安装 Docker
sudo yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 启动 Docker
sudo systemctl start docker
sudo systemctl enable docker
```

### 3.2 配置 Docker 权限
```bash
# 将当前用户添加到 docker 组
sudo usermod -aG docker $USER

# 需要重新登录才能生效，或者执行
newgrp docker

# 验证（不需要 sudo）
docker run hello-world
```

### 3.3 验证 Docker Compose
```bash
docker compose version
# 应该显示: Docker Compose version v2.x.x
```

---

## 📦 步骤 4: 部署工具容器

### 4.1 创建项目目录
```bash
cd ~
mkdir -p molagent
cd molagent

# 创建 Docker 数据目录
mkdir -p docker-data/{postgres,minio,gnina,vina,chemprop}
```

### 4.2 创建 docker-compose.yml

创建文件 `~/molagent/docker-compose.yml`:

```yaml
version: '3.8'

services:
  # PostgreSQL 数据库
  postgres:
    image: postgres:15-alpine
    container_name: medagent-postgres
    environment:
      POSTGRES_DB: medagent
      POSTGRES_USER: medagent
      POSTGRES_PASSWORD: medagent_secure_password_2024
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - ./docker-data/postgres:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U medagent"]
      interval: 10s
      timeout: 5s
      retries: 5

  # MinIO 对象存储
  minio:
    image: minio/minio:latest
    container_name: medagent-minio
    environment:
      MINIO_ROOT_USER: medagent
      MINIO_ROOT_PASSWORD: medagent_minio_2024
    volumes:
      - ./docker-data/minio:/data
    ports:
      - "9000:9000"
      - "9001:9001"
    command: server /data --console-address ":9001"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3

  # GNINA (对接工具)
  gnina:
    image: gnina/gnina:latest
    container_name: medagent-gnina
    volumes:
      - ./docker-data/gnina:/data
    restart: unless-stopped
    command: tail -f /dev/null  # 保持运行

  # Chemprop (ADMET 预测)
  chemprop:
    image: chemprop/chemprop:latest
    container_name: medagent-chemprop
    volumes:
      - ./docker-data/chemprop:/data
    ports:
      - "5000:5000"
    restart: unless-stopped
    command: tail -f /dev/null  # 保持运行

networks:
  default:
    name: medagent-network
```

### 4.3 启动容器
```bash
cd ~/molagent

# 拉取镜像
docker compose pull

# 启动所有容器
docker compose up -d

# 查看状态
docker compose ps

# 查看日志
docker compose logs -f
```

### 4.4 验证容器
```bash
# 检查所有容器是否运行
docker ps

# 测试 PostgreSQL
docker exec -it medagent-postgres psql -U medagent -d medagent -c "SELECT version();"

# 测试 MinIO
curl http://localhost:9000/minio/health/live

# 测试 GNINA
docker exec medagent-gnina gnina --version

# 查看 Chemprop
docker exec medagent-chemprop python -c "import chemprop; print(chemprop.__version__)"
```

---

## 🐍 步骤 5: 创建 Python 虚拟环境

### 5.1 创建虚拟环境
```bash
cd ~/molagent

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 升级 pip
pip install --upgrade pip setuptools wheel
```

### 5.2 安装系统依赖

#### Ubuntu/Debian
```bash
# 化学工具依赖
sudo apt install -y \
    libopenbabel-dev \
    openbabel \
    swig \
    libboost-all-dev \
    libeigen3-dev

# RDKit 依赖
sudo apt install -y \
    librdkit-dev \
    python3-rdkit

# 数据库客户端
sudo apt install -y \
    postgresql-client \
    libpq-dev
```

#### CentOS/RHEL
```bash
sudo yum install -y \
    openbabel \
    openbabel-devel \
    boost-devel \
    eigen3-devel \
    postgresql-devel \
    swig
```

---

## 📝 步骤 6: 准备项目依赖文件

### 6.1 创建 requirements.txt（如果你还没上传代码）

创建 `~/molagent/requirements-server.txt`:

```txt
# Web框架
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
httpx>=0.27.0
python-multipart>=0.0.12

# 数据库
sqlalchemy>=2.0.35
psycopg[binary]>=3.2.0
alembic>=1.13.0

# 对象存储
minio>=7.2.0

# LLM
openai>=1.0.0

# 配置管理
pydantic-settings>=2.6.0
python-dotenv>=1.0.0

# 化学工具
rdkit>=2023.9.1
datamol>=0.12.0

# ADMET (可选，如果不用Docker)
admet-ai==2.0.1

# RAG
pypdf>=5.0.0

# 工具
pyyaml>=6.0
```

### 6.2 安装依赖（先安装基础包）
```bash
source ~/molagent/venv/bin/activate

# 基础依赖
pip install fastapi uvicorn httpx python-multipart
pip install sqlalchemy psycopg[binary] alembic
pip install minio openai pydantic-settings python-dotenv
pip install pyyaml pypdf

# 化学工具（可能需要时间）
pip install rdkit datamol --break-system-packages || pip install rdkit datamol

# 如果 RDKit 安装失败，使用 conda
# conda install -c conda-forge rdkit
```

---

## 🔧 步骤 7: 配置环境变量

### 7.1 创建 .env 文件

创建 `~/molagent/.env`:

```bash
# 应用配置
APP_NAME=MedAgent
APP_ENV=production
DEBUG=false

# 数据库配置
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=medagent
POSTGRES_USER=medagent
POSTGRES_PASSWORD=medagent_secure_password_2024
DATABASE_URL=postgresql://medagent:medagent_secure_password_2024@localhost:5432/medagent

# MinIO 配置
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=medagent
MINIO_SECRET_KEY=medagent_minio_2024
MINIO_SECURE=false
MINIO_BUCKET=medagent-storage

# LLM API Keys（需要填写你的真实 API Key）
MEDAGENT_DASHSCOPE_API_KEY=your_dashscope_api_key_here
MEDAGENT_DEEPSEEK_API_KEY=your_deepseek_api_key_here

# Docker 工具配置
GNINA_DOCKER_IMAGE=gnina/gnina:latest
VINA_DOCKER_IMAGE=autodock/vina:latest
CHEMPROP_DOCKER_IMAGE=chemprop/chemprop:latest

# 工作目录
WORK_DIR=/home/MolAgent/molagent/workspace
TEMP_DIR=/tmp/medagent
```

### 7.2 创建工作目录
```bash
mkdir -p ~/molagent/workspace
mkdir -p /tmp/medagent
chmod 755 ~/molagent/workspace
```

---

## ✅ 步骤 8: 验证部署

### 8.1 创建验证脚本

创建 `~/molagent/verify_deployment.sh`:

```bash
#!/bin/bash

echo "=================================="
echo "MedAgent 部署验证脚本"
echo "=================================="
echo ""

PASS=0
TOTAL=0

# 1. Python 版本
echo "1. 检查 Python 版本"
TOTAL=$((TOTAL + 1))
PYTHON_VERSION=$(python3 --version | grep -oP '\d+\.\d+' | head -1)
if (( $(echo "$PYTHON_VERSION >= 3.11" | bc -l) )); then
    echo "   ✓ Python $PYTHON_VERSION"
    PASS=$((PASS + 1))
else
    echo "   ✗ Python 版本不足 (<3.11)"
fi
echo ""

# 2. Docker
echo "2. 检查 Docker"
TOTAL=$((TOTAL + 1))
if docker ps > /dev/null 2>&1; then
    echo "   ✓ Docker 运行正常"
    PASS=$((PASS + 1))
else
    echo "   ✗ Docker 未运行或无权限"
fi
echo ""

# 3. 容器状态
echo "3. 检查容器状态"
CONTAINERS=("medagent-postgres" "medagent-minio" "medagent-gnina" "medagent-chemprop")
for container in "${CONTAINERS[@]}"; do
    TOTAL=$((TOTAL + 1))
    if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        echo "   ✓ $container 运行中"
        PASS=$((PASS + 1))
    else
        echo "   ✗ $container 未运行"
    fi
done
echo ""

# 4. PostgreSQL 连接
echo "4. 检查 PostgreSQL 连接"
TOTAL=$((TOTAL + 1))
if docker exec medagent-postgres psql -U medagent -d medagent -c "SELECT 1;" > /dev/null 2>&1; then
    echo "   ✓ PostgreSQL 连接成功"
    PASS=$((PASS + 1))
else
    echo "   ✗ PostgreSQL 连接失败"
fi
echo ""

# 5. MinIO 健康检查
echo "5. 检查 MinIO"
TOTAL=$((TOTAL + 1))
if curl -sf http://localhost:9000/minio/health/live > /dev/null 2>&1; then
    echo "   ✓ MinIO 运行正常"
    PASS=$((PASS + 1))
else
    echo "   ✗ MinIO 无法访问"
fi
echo ""

# 6. Python 虚拟环境
echo "6. 检查 Python 虚拟环境"
TOTAL=$((TOTAL + 1))
if [ -f "venv/bin/activate" ]; then
    echo "   ✓ 虚拟环境存在"
    PASS=$((PASS + 1))
else
    echo "   ✗ 虚拟环境不存在"
fi
echo ""

# 7. Python 包
echo "7. 检查关键 Python 包"
source venv/bin/activate 2>/dev/null
PACKAGES=("fastapi" "sqlalchemy" "rdkit")
for pkg in "${PACKAGES[@]}"; do
    TOTAL=$((TOTAL + 1))
    if python -c "import $pkg" 2>/dev/null; then
        echo "   ✓ $pkg 已安装"
        PASS=$((PASS + 1))
    else
        echo "   ✗ $pkg 未安装"
    fi
done
echo ""

# 汇总
echo "=================================="
echo "验证结果: $PASS/$TOTAL"
echo "=================================="

if [ $PASS -eq $TOTAL ]; then
    echo "✅ 所有检查通过，环境就绪！"
    exit 0
else
    FAILED=$((TOTAL - PASS))
    echo "⚠️  有 $FAILED 项检查失败"
    exit 1
fi
```

### 8.2 运行验证
```bash
cd ~/molagent
chmod +x verify_deployment.sh
./verify_deployment.sh
```

---

## 🔍 步骤 9: 常见问题排查

### 问题 1: Docker 权限拒绝
```bash
# 解决方法
sudo usermod -aG docker $USER
newgrp docker

# 或重新登录
exit
# 重新 SSH 连接
```

### 问题 2: PostgreSQL 连接失败
```bash
# 检查容器日志
docker logs medagent-postgres

# 重启容器
docker restart medagent-postgres

# 手动连接测试
docker exec -it medagent-postgres psql -U medagent -d medagent
```

### 问题 3: RDKit 安装失败
```bash
# 使用系统包
sudo apt install python3-rdkit

# 或使用 conda
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
conda install -c conda-forge rdkit
```

### 问题 4: 磁盘空间不足
```bash
# 检查磁盘
df -h

# 清理 Docker
docker system prune -a

# 清理旧容器和镜像
docker container prune
docker image prune -a
```

---

## 📊 步骤 10: 性能优化建议

### 10.1 Docker 资源限制

编辑 `docker-compose.yml`，添加资源限制：

```yaml
services:
  postgres:
    # ... 其他配置
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G
```

### 10.2 PostgreSQL 调优

```bash
# 编辑 PostgreSQL 配置
docker exec -it medagent-postgres bash
vi /var/lib/postgresql/data/postgresql.conf

# 推荐配置（根据你的服务器内存调整）
# shared_buffers = 2GB
# effective_cache_size = 6GB
# maintenance_work_mem = 512MB
# checkpoint_completion_target = 0.9
# wal_buffers = 16MB
# default_statistics_target = 100
# random_page_cost = 1.1
# effective_io_concurrency = 200
# work_mem = 10MB
# min_wal_size = 1GB
# max_wal_size = 4GB

# 重启 PostgreSQL
docker restart medagent-postgres
```

---

## 📚 下一步

环境配置完成后：

1. **上传代码**
   ```bash
   # 在本地
   cd C:\Users\zhihong\Desktop\small-molecule-drug-design-agent
   
   # 打包（排除不需要的文件）
   tar -czf medagent-code.tar.gz \
       --exclude='.git' \
       --exclude='__pycache__' \
       --exclude='.venv' \
       --exclude='*.pyc' \
       src/ config.yaml migrations/
   
   # 上传到服务器
   scp medagent-code.tar.gz MolAgent@10.3.95.48:~/molagent/
   ```

2. **在服务器解压**
   ```bash
   cd ~/molagent
   tar -xzf medagent-code.tar.gz
   ```

3. **运行数据库迁移**
   ```bash
   source venv/bin/activate
   cd ~/molagent
   
   # 初始化数据库
   python -c "from src.medagent.db.models import Base; from sqlalchemy import create_engine; engine = create_engine('postgresql://medagent:medagent_secure_password_2024@localhost:5432/medagent'); Base.metadata.create_all(engine)"
   
   # 运行当前版本需要的全部幂等迁移
   export MEDAGENT_DATABASE_URL='postgresql+psycopg://medagent:medagent_secure_password_2024@localhost:5432/medagent'
   python migrations/run_all.py
   ```

4. **启动应用**
   ```bash
   source venv/bin/activate
   cd ~/molagent
   
   export PYTHONPATH="$PWD/src"

   # 开发模式
   python -m uvicorn medagent.api.app:create_app --factory --host 0.0.0.0 --port 8000 --reload
   
   # 生产模式
   python -m uvicorn medagent.api.app:create_app --factory --host 0.0.0.0 --port 8000 --workers 4
   ```

---

## 📞 获取帮助

如果遇到问题：
1. 查看 Docker 日志：`docker compose logs -f`
2. 查看应用日志：`tail -f ~/molagent/logs/app.log`
3. 运行验证脚本：`./verify_deployment.sh`

---

**部署检查清单完成后，请执行验证脚本确认一切正常！**
