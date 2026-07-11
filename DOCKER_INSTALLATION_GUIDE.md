# 🚀 Docker工具安装执行指南

## 自动安装（推荐）

### 方法1：双击运行批处理文件
1. 找到文件：`scripts\build_docker_tools.bat`
2. 双击运行
3. 等待10-30分钟完成构建

### 方法2：PowerShell脚本
```powershell
cd C:\Users\zhihong\Desktop\small-molecule-drug-design-agent
.\scripts\build_docker_tools.ps1
```

### 方法3：命令行逐个构建
```bash
cd C:\Users\zhihong\Desktop\small-molecule-drug-design-agent

# 1. 拉取GNINA公共镜像（最快）
docker pull gnina/gnina:latest

# 2. 构建Chemprop（必需，~5-10分钟）
docker compose build chemprop

# 3. 构建DiffDock（可选，~10-15分钟）
docker compose build diffdock

# 4. 构建REINVENT4（可选，~3-5分钟）
docker compose build reinvent4

# 5. 构建AutoGrow4（可选，~5-10分钟）
docker compose build autogrow4
```

---

## 分步说明

### 前置条件检查
```bash
# 检查Docker是否安装
docker --version

# 检查Docker是否运行
docker ps
```

如果Docker未运行，请启动Docker Desktop。

---

### 工具1: GNINA（分子对接）

**优先级：** 高  
**构建时间：** 1-2分钟（拉取公共镜像）

```bash
docker pull gnina/gnina:latest
```

**测试：**
```bash
docker run --rm gnina/gnina:latest --version
```

---

### 工具2: Chemprop（ADMET预测）

**优先级：** 高（你已部署）  
**构建时间：** 5-10分钟

```bash
docker compose build chemprop
```

**测试：**
```bash
docker compose run --rm chemprop --version
python scripts\manage_docker_tools.py test-chemprop
```

---

### 工具3: DiffDock（分子对接）

**优先级：** 中  
**构建时间：** 10-15分钟

```bash
docker compose build diffdock
```

**测试：**
```bash
docker compose run --rm diffdock -m diffdock --help
```

---

### 工具4: REINVENT4（分子生成）

**优先级：** 中  
**构建时间：** 3-5分钟

```bash
docker compose build reinvent4
```

**测试：**
```bash
docker compose run --rm reinvent4 --help
```

---

### 工具5: AutoGrow4（分子生成）

**优先级：** 低  
**构建时间：** 5-10分钟

```bash
docker compose build autogrow4
```

**测试：**
```bash
docker compose run --rm autogrow4 -m autogrow4 --help
```

---

## 验证安装

### 检查所有工具状态
```bash
python scripts\check_tools.py --verbose
```

### 检查Docker镜像
```bash
docker images | findstr "chemprop gnina diffdock reinvent autogrow"
```

### 管理工具
```bash
# 查看状态
python scripts\manage_docker_tools.py status

# 测试Chemprop
python scripts\manage_docker_tools.py test-chemprop

# 测试其他工具
python scripts\manage_docker_tools.py test chemprop
python scripts\manage_docker_tools.py test diffdock
```

---

## 常见问题

### Q: Docker构建很慢？
A: 第一次构建需要下载基础镜像和依赖，请耐心等待。可以同时做其他事情。

### Q: 构建失败？
A: 
1. 检查Docker Desktop是否运行
2. 检查网络连接
3. 查看错误日志
4. 尝试重新构建：`docker compose build --no-cache <service>`

### Q: 磁盘空间不足？
A: Docker镜像较大，建议预留20-30GB空间。可以清理旧镜像：
```bash
docker system prune -a
```

### Q: 需要所有工具吗？
A: 
- **必需：** Chemprop（ADMET预测）
- **推荐：** GNINA（分子对接）
- **可选：** DiffDock, REINVENT4, AutoGrow4

---

## 预期结果

构建成功后，你应该看到：

```
✅ GNINA拉取成功
✅ Chemprop构建成功
✅ DiffDock构建成功
✅ REINVENT4构建成功
✅ AutoGrow4构建成功
```

运行 `python scripts\check_tools.py --verbose` 应该显示：

```
✅ RDKit
   版本: 2023.09.1
   
✅ Chemprop
   模式: docker
   镜像: chemprop:latest
   
✅ GNINA
   模式: docker
   镜像: gnina/gnina:latest

... (其他工具)

可用工具: 5/7
```

---

## 启动服务

构建完成后，可以启动需要的服务：

```bash
# 启动Chemprop
docker compose up -d chemprop

# 查看日志
docker compose logs -f chemprop

# 停止服务
docker compose stop chemprop
```

---

## 下一步

1. ✅ 运行 `scripts\build_docker_tools.bat` 
2. ✅ 等待构建完成（10-30分钟）
3. ✅ 运行 `python scripts\check_tools.py --verbose` 验证
4. ✅ 运行 `python scripts\manage_docker_tools.py test-chemprop` 测试
5. ✅ 开始使用工具进行分子评估！

---

**现在请执行：双击 `scripts\build_docker_tools.bat` 文件开始构建！**
