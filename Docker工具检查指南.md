# Docker计算工具状态检查指南

**日期**: 2026-07-11  
**目的**: 验证Docker计算工具是否构建完成

---

## 🔍 检查方法

### 方法1：使用自动检查脚本（推荐）

在项目根目录运行：

```cmd
check_docker_tools.bat
```

这个脚本会检查所有6个Docker工具镜像的状态。

---

### 方法2：手动检查

在项目根目录打开PowerShell或CMD，运行：

```cmd
# 1. 检查Docker是否运行
docker ps

# 2. 查看所有工具镜像
docker images | findstr "chemprop\|diffdock\|reinvent\|autogrow\|vina\|gnina"

# 3. 逐个检查镜像
docker image inspect chemprop:latest
docker image inspect diffdock:latest
docker image inspect reinvent4:latest
docker image inspect autogrow4:latest
docker image inspect vina:latest
docker image inspect gnina/gnina:latest
```

---

## 📋 应该看到的结果

### ✅ 如果构建成功（119分钟完成）

你应该看到以下镜像：

| 镜像名称 | 标签 | 状态 | 用途 |
|---------|------|------|------|
| chemprop | latest | ✅ 已构建 | ADMET预测 |
| diffdock | latest | ✅ 已构建 | 扩散模型对接 |
| reinvent4 | latest | ✅ 已构建 | 强化学习分子生成 |
| autogrow4 | latest | ✅ 已构建 | 遗传算法分子生成 |
| vina | latest | ✅ 已构建 | AutoDock Vina对接 |
| gnina/gnina | latest | ✅ 已下载 | GNINA对接 |

**预期输出示例**:
```
REPOSITORY          TAG       SIZE        CREATED
chemprop            latest    2.5GB       2 hours ago
diffdock            latest    8.3GB       2 hours ago
reinvent4           latest    3.1GB       2 hours ago
autogrow4           latest    2.8GB       2 hours ago
vina                latest    800MB       2 hours ago
gnina/gnina         latest    1.2GB       2 hours ago
```

---

### ❌ 如果构建失败或未完成

你可能会看到：
- `Error: No such image: chemprop:latest`
- 镜像列表为空
- 只有部分镜像存在

**解决方法**:
```cmd
# 重新构建所有工具
setup_and_build.bat

# 或单独构建失败的工具
docker-compose build chemprop
docker-compose build diffdock
docker-compose build reinvent4
docker-compose build autogrow4
docker-compose build vina
docker pull gnina/gnina:latest
```

---

## 🧪 验证工具功能

### 1. 启动基础设施

```cmd
docker-compose up -d postgres minio
```

### 2. 测试RDKit（本地Python）

```cmd
# 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 安装RDKit（如果还没安装）
pip install rdkit

# 测试
python -c "from rdkit import Chem; print('RDKit可用:', Chem.MolFromSmiles('CCO') is not None)"
```

### 3. 运行完整工具检测

```cmd
python scripts\check_tools.py --verbose --test
```

**预期结果**:
- RDKit: ✅（Python包）
- 其他工具: ✅（Docker模式）或 ❌（如果镜像未构建）

---

## 📊 根据你的情况判断

你提到脚本显示：
```
========================================
Setup finished in about 119.2 minutes
========================================
All selected tools are ready.
```

这表明构建**应该已完成**！

### 下一步验证

1. **运行检查脚本**:
   ```cmd
   cd C:\Users\zhihong\Desktop\small-molecule-drug-design-agent
   check_docker_tools.bat
   ```

2. **查看结果**:
   - 如果看到6个 ✅ → 工具已就绪，可以开始开发Agent
   - 如果看到 ❌ → 某些镜像构建失败，需要重新构建

3. **运行集成测试**:
   ```cmd
   .\.venv\Scripts\Activate.ps1
   pytest tests\test_tools_integration.py -v
   pytest tests\test_docking_adapters.py -v
   pytest tests\test_admet_adapter.py -v
   ```

---

## 🎯 如果工具已就绪

恭喜！你的计算工具已经准备好了。下一步：

### 立即可做的事情

1. **验证工具功能**:
   ```cmd
   python scripts\check_tools.py --verbose --test
   python scripts\manage_docker_tools.py status
   ```

2. **运行Agent工作流示例**:
   ```cmd
   python examples\agent_workflow_example.py
   ```

3. **开始开发缺失的Agent**:
   - 创建 `src/medagent/agents/generator.py`
   - 创建 `src/medagent/agents/filter.py`
   - 创建 `src/medagent/agents/docking.py`
   - 创建 `src/medagent/agents/admet.py`
   - 创建 `src/medagent/agents/synthesis.py`

---

## 📝 记录检查结果

请在Windows主机上运行 `check_docker_tools.bat`，然后告诉我结果，我可以：

1. **如果都是 ✅**: 生成"Agent开发任务清单"
2. **如果有 ❌**: 帮助你诊断和修复构建问题

---

## 🔧 常见问题

### Q: Docker命令找不到
**A**: 确保Docker Desktop正在运行

### Q: 镜像构建失败
**A**: 检查：
- 网络连接（中国需要镜像加速）
- 磁盘空间（至少需要30GB）
- Docker配置（`docker/daemon.json`）

### Q: RDKit找不到
**A**: 在虚拟环境中安装：
```cmd
.\.venv\Scripts\Activate.ps1
pip install rdkit
```

---

**下一步**: 请运行 `check_docker_tools.bat` 并告诉我结果！
