# GPU 真实验证指南

## ⚠️ 重要说明

我的测试环境（Linux VM）**没有 Docker 和 GPU**，所以我只能验证：
- ✅ 代码逻辑正确
- ✅ 命令中包含 `--gpus all` 参数
- ✅ GPU 检测函数存在
- ✅ 单元测试通过

但我**无法验证**：
- ❌ Docker 是否真的能访问 GPU
- ❌ 化学工具是否真的使用了 GPU
- ❌ GPU 模式下的实际性能

---

## 🧪 真实 GPU 验证步骤

### 步骤 1: 基础 Docker GPU 测试

在你的本地机器（Windows/Linux）上运行：

```bash
# 测试 Docker 是否能访问 GPU
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

**期望结果**:
```
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 535.xx.xx    Driver Version: 535.xx.xx    CUDA Version: 12.0   |
|-------------------------------+----------------------+----------------------+
| GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
| ...                                                                         |
+-----------------------------------------------------------------------------+
```

**如果失败**:
- Windows (WSL2): 安装 [NVIDIA Container Toolkit for WSL2](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- Linux: 安装 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

---

### 步骤 2: 运行集成测试脚本

我已经创建了一个测试脚本：`scripts/test_gpu_integration.py`

```bash
cd C:\Users\zhihong\Desktop\small-molecule-drug-design-agent
python scripts/test_gpu_integration.py
```

这个脚本会测试：
1. Docker GPU 基础可用性
2. gnina 是否能使用 GPU
3. chemprop 是否能使用 GPU
4. 代码中的 GPU 检测函数
5. 容器超时清理功能

---

### 步骤 3: 真实对接任务测试

运行一个真实的分子对接任务，观察：

#### 3a. 监控 GPU 使用（另一个终端）

```bash
# 持续监控 GPU
watch -n 1 nvidia-smi
```

**期望看到**: 在对接运行时，GPU 利用率和显存使用率上升

#### 3b. 运行对接任务

```python
# 你的项目代码中运行一个对接任务
from medagent.services.docking_adapters import (
    DockingToolRequest,
    run_external_docking,
    check_gnina_available,
)

# 准备一个简单的测试
request = DockingToolRequest(
    receptor_file="path/to/receptor.pdb",
    ligand_file="path/to/ligand.sdf",
    output_dir="./test_output",
    grid_center=[10.0, 15.0, 20.0],
    grid_size=[20.0, 20.0, 20.0],
    molecule_id="TEST-001",
    timeout_seconds=300,
)

tool_status = {
    "gnina": check_gnina_available(),
    "vina": {"available": False},
    "diffdock": {"available": False},
}

print("开始对接...")
result = run_external_docking(request, tool_status)

print(f"成功: {result.success}")
print(f"Vina 分数: {result.vina_score}")
print(f"运行时间: {result.runtime_seconds:.2f}s")
print(f"警告: {result.warnings}")
```

**关键观察点**:
1. 运行时间应该显著缩短（如果之前超时，现在应该 < 1 分钟）
2. 警告中**不应该**有 `gnina_running_in_cpu_mode`（如果 GPU 可用）
3. `nvidia-smi` 应该显示 gnina 进程在使用 GPU

---

### 步骤 4: 性能对比测试

#### GPU 模式 vs CPU 模式

```bash
# 1. GPU 模式（默认）
time docker run --rm --gpus all \
  -v "$(pwd)/data:/data" \
  gnina/gnina:latest gnina \
  -r /data/receptor.pdb \
  -l /data/ligand.sdf \
  -o /data/pose_gpu.sdf \
  --center_x 10 --center_y 15 --center_z 20 \
  --size_x 20 --size_y 20 --size_z 20

# 2. CPU 模式（禁用 CNN）
time docker run --rm \
  -v "$(pwd)/data:/data" \
  gnina/gnina:latest gnina \
  -r /data/receptor.pdb \
  -l /data/ligand.sdf \
  -o /data/pose_cpu.sdf \
  --center_x 10 --center_y 15 --center_z 20 \
  --size_x 20 --size_y 20 --size_z 20 \
  --cnn_scoring none
```

**期望结果**:
- GPU 模式: 5-30 秒
- CPU 模式（带 `--cnn_scoring none`）: 30-60 秒
- CPU 模式（不带优化）: 5+ 分钟（会超时）

---

### 步骤 5: 验证容器清理

#### 5a. 检查现有残留

```bash
# 查看所有容器（包括已停止的）
docker ps -a | grep -E "gnina|vina|diffdock|chemprop"
```

如果有很多旧容器，先清理：

```powershell
# Windows PowerShell
docker ps -a --filter "ancestor=gnina/gnina" --format "{{.ID}}" | ForEach-Object { docker rm -f $_ }
```

#### 5b. 运行对接任务后检查

```bash
# 运行对接...
# 运行完成后立即检查

docker ps -a | grep -E "gnina|vina|diffdock|chemprop"
```

**期望结果**: 应该**没有**残留容器（因为所有容器都是 `--rm` 且超时会被清理）

---

## 🔍 问题诊断

### 问题 1: GPU 检测失败

**症状**: `_check_gpu_available()` 返回 `False`

**可能原因**:
1. NVIDIA Container Toolkit 未安装
2. Docker daemon 配置不正确
3. 没有 NVIDIA GPU 硬件

**解决方法**:
```bash
# 检查 nvidia-smi 是否可用
nvidia-smi

# 检查 Docker 是否看到 GPU
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi

# 检查 Docker daemon 配置
cat /etc/docker/daemon.json
# 应该包含:
# {
#   "runtimes": {
#     "nvidia": {
#       "path": "nvidia-container-runtime",
#       "runtimeArgs": []
#     }
#   }
# }
```

---

### 问题 2: gnina 仍然很慢

**症状**: 即使代码修复了，对接仍然超时

**可能原因**:
1. GPU 未真正使用
2. 有大量残留容器
3. Docker 资源限制

**诊断步骤**:
```bash
# 1. 监控 GPU 使用
nvidia-smi dmon -s u

# 2. 检查残留容器
docker ps -a | wc -l

# 3. 检查 Docker 资源
docker stats

# 4. 查看 gnina 命令
# 在 result.command 中应该看到:
# ["docker", "run", "--rm", "--name", "gnina_xxx", "--gpus", "all", ...]
```

---

### 问题 3: 容器仍然残留

**症状**: 运行后 `docker ps -a` 看到很多容器

**可能原因**:
1. 超时清理函数未被调用
2. Docker 权限问题

**诊断步骤**:
```python
# 手动测试清理函数
from medagent.services.docking_adapters import _cleanup_docker_container

# 创建测试容器
import subprocess
subprocess.Popen(["docker", "run", "--rm", "--name", "test123", "alpine", "sleep", "3600"])

# 清理
_cleanup_docker_container("test123")

# 检查是否删除
subprocess.run(["docker", "ps", "-a", "--filter", "name=test123"])
```

---

## 📊 验证清单

用这个清单验证修复是否真正生效：

- [ ] **基础 GPU 测试**: `docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi` 成功
- [ ] **代码 GPU 检测**: `_check_gpu_available()` 返回 `True`
- [ ] **gnina GPU 命令**: Docker 命令包含 `--gpus all`
- [ ] **gnina CPU 命令**: CPU 模式包含 `--cnn_scoring none`
- [ ] **实际 GPU 使用**: `nvidia-smi` 显示 Docker 进程使用 GPU
- [ ] **性能提升**: 对接时间从 5+ 分钟降到 < 1 分钟
- [ ] **无残留容器**: 运行后 `docker ps -a` 干净
- [ ] **超时清理**: 模拟超时后容器被删除
- [ ] **单元测试**: 所有 13 个测试通过

---

## 🎯 最小可验证示例

如果以上都太复杂，用这个最简单的测试：

```python
#!/usr/bin/env python
"""最简单的 GPU 验证"""

import subprocess

print("测试 1: Docker GPU 基础")
try:
    result = subprocess.run(
        ["docker", "run", "--rm", "--gpus", "all", "nvidia/cuda:12.0-base", "nvidia-smi"],
        capture_output=True,
        timeout=30,
    )
    if result.returncode == 0:
        print("✅ GPU 可用")
    else:
        print("❌ GPU 不可用")
        print(result.stderr.decode())
except Exception as e:
    print(f"❌ 错误: {e}")

print("\n测试 2: 代码 GPU 检测")
import sys
sys.path.insert(0, "src")
from medagent.services.docking_adapters import _check_gpu_available

if _check_gpu_available():
    print("✅ 代码检测到 GPU")
else:
    print("⚠️ 代码未检测到 GPU（将使用 CPU 模式）")
```

---

## 📞 需要帮助？

如果你运行了验证脚本后：
1. 把输出发给我，我帮你分析
2. 或者告诉我具体哪个测试失败了
3. 附上 `nvidia-smi` 和 `docker ps -a` 的输出

我的测试只保证了**代码正确性**，真实 GPU 使用需要你在本地验证！
