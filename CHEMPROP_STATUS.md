# ⚠️ Chemprop Docker镜像说明

## 问题说明

你看到的 "Dockerfile不存在" 错误是PowerShell脚本的路径检查问题，实际上：

✅ **Dockerfile确实存在：** `docker/chemprop/Dockerfile`  
✅ **文件内容正确**  
✅ **之前的构建应该是成功的**

---

## 检查Chemprop是否已存在

运行以下命令检查Chemprop镜像是否已经构建：

```bash
docker images | findstr chemprop
```

### 如果看到输出：
```
small-molecule-drug-design-agent-chemprop    latest    xxx    xxx    xxx
```

**说明Chemprop已经构建好了！** ✅ 你可以直接使用，不需要重新构建。

---

## 验证Chemprop可用性

### 方法1：使用检测脚本
```bash
python scripts\check_tools.py --verbose
```

应该看到：
```
✅ Chemprop
   模式: docker
   镜像: small-molecule-drug-design-agent-chemprop:latest
```

### 方法2：直接测试Docker
```bash
docker compose run --rm chemprop --version
```

### 方法3：完整测试
```bash
python scripts\manage_docker_tools.py test chemprop
```

---

## 如果Chemprop真的不存在

### 使用新的构建脚本

我已经创建了一个更可靠的脚本：

**双击运行：** `scripts\build_all_tools.bat`

这个脚本会：
1. 检查Docker状态
2. 逐个构建所有工具
3. 显示详细的构建进度
4. 统计成功/失败数量

---

## 手动构建Chemprop

如果自动脚本有问题，可以手动构建：

```bash
cd C:\Users\zhihong\Desktop\small-molecule-drug-design-agent

# 检查Dockerfile
dir docker\chemprop\Dockerfile

# 构建镜像
docker compose build chemprop

# 测试镜像
docker compose run --rm chemprop --version
```

---

## Chemprop配置详情

### Dockerfile内容
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Chemprop
RUN pip install --no-cache-dir chemprop

# Create directories for I/O
RUN mkdir -p /data/input /data/output /data/models

# Default entrypoint
ENTRYPOINT ["chemprop"]
CMD ["--help"]
```

### Docker Compose配置
```yaml
chemprop:
  build: docker/chemprop
  volumes:
    - ./data/predictions:/data/output
    - ./data/models:/data/models
  command: ["--help"]
  profiles:
    - tools
```

---

## 故障排除

### 问题1：PowerShell脚本报错
**原因：** PowerShell的 `Test-Path` 在某些情况下可能不识别反斜杠路径  
**解决：** 使用新的 `build_all_tools.bat` 批处理脚本

### 问题2：Docker Compose找不到服务
**检查：**
```bash
docker compose config | findstr chemprop
```

### 问题3：镜像构建失败
**查看日志：**
```bash
docker compose build --no-cache chemprop
```

---

## 推荐操作流程

### 第1步：检查现有镜像
```bash
docker images | findstr chemprop
```

### 第2步：如果已存在，验证可用性
```bash
python scripts\check_tools.py --verbose
```

### 第3步：如果不存在或有问题，重新构建
```bash
# 方法A：使用新脚本
scripts\build_all_tools.bat

# 方法B：手动构建
docker compose build chemprop
```

### 第4步：测试功能
```bash
python scripts\manage_docker_tools.py test chemprop
```

---

## 关于"Chemprop已经弄好了"

如果你之前已经成功构建了Chemprop，那么：

1. **镜像仍然存在** - Docker镜像不会自动消失
2. **可以直接使用** - 不需要重新构建
3. **忽略脚本错误** - PowerShell脚本的路径检查问题不影响实际使用

**验证方法：**
```bash
# 查看镜像
docker images | findstr chemprop

# 如果看到输出，说明镜像存在
# 直接运行检测脚本验证
python scripts\check_tools.py --verbose
```

---

## 快速解决方案

**现在立即执行：**

```bash
# 1. 检查Chemprop是否已存在
docker images | findstr chemprop

# 2. 如果存在，验证功能
python scripts\check_tools.py --verbose

# 3. 如果功能正常，说明Chemprop已就绪，忽略脚本错误
# 4. 如果不存在或不工作，运行：
scripts\build_all_tools.bat
```

---

**总结：你的Chemprop很可能已经构建好了，只是PowerShell脚本的路径检查有问题。先运行检测脚本确认状态！** ✅
