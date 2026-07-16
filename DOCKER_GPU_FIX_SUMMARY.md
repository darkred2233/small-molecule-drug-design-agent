# Docker GPU 支持和超时清理修复总结

## 问题诊断

### 根本原因
1. **Bug #1: gnina 在 CPU 模式下极慢**
   - gnina 默认使用 CNN scoring，在 CPU 上处理一个分子需要 5+ 分钟
   - 没有 GPU 支持的 Docker 容器导致每次对接都超时

2. **Bug #2: 超时后容器不清理（更严重）**
   - `subprocess.run(timeout=X)` 只杀死 Python 子进程
   - Docker 容器继续在后台运行，争抢 CPU 资源
   - **恶性循环**: 残留容器越多 → CPU 更拥挤 → 新任务更容易超时 → 产生更多残留

3. **影响范围**: 所有使用 Docker 的化学计算工具
   - gnina (分子对接)
   - vina (分子对接)
   - diffdock (分子对接)
   - chemprop (ADMET 预测)
   - aizynthfinder (逆合成)
   - autogrow4 (分子生成)

---

## 修复内容

### 1. **docking_adapters.py** (gnina, vina, diffdock)

#### 添加的功能：
- ✅ **GPU 支持**: 添加 `--gpus all` 到 Docker 命令
- ✅ **GPU 检测**: `_check_gpu_available()` 自动检测 GPU 是否可用
- ✅ **CPU 友好参数**: gnina 在 CPU 模式下添加 `--cnn_scoring none`
- ✅ **容器命名**: 每个容器添加唯一名称（基于 molecule_id + 时间戳）
- ✅ **超时清理**: `_cleanup_docker_container()` 在超时时强制删除容器
- ✅ **超时标记**: 区分超时 (`exit_code=None`) 和普通失败

#### 修改的函数：
```python
# 新增辅助函数
_check_gpu_available()           # 检测 GPU 是否可用
_extract_container_name()        # 从命令中提取容器名
_cleanup_docker_container()      # 强制删除容器

# 修改的函数
build_gnina_docker_command()     # 添加 GPU 支持、容器命名、CPU 参数
build_vina_docker_command()      # 添加容器命名
run_gnina_docker_docking()       # 添加 GPU 检测和 CPU 模式处理
_run_diffdock_docker()           # 添加 GPU 支持和容器命名
_run_command()                   # 添加超时时的容器清理
_tool_warnings()                 # 区分超时和普通失败
```

---

### 2. **admet_adapter.py** (chemprop)

#### 添加的功能：
- ✅ **GPU 支持**: chemprop 添加 `--gpus all`
- ✅ **容器命名和清理**: 超时时删除容器
- ✅ **GPU 状态警告**: 如果没有 GPU 会记录 warning

#### 修改的函数：
```python
# 新增辅助函数
_check_gpu_available()           # 检测 GPU
_cleanup_docker_container()      # 清理容器

# 修改的函数
_run_chemprop_docker()           # 添加 GPU 支持和超时清理
```

---

### 3. **aizynthfinder_adapter.py**

#### 添加的功能：
- ✅ **GPU 支持**: 添加 `--gpus all`（可选，但有帮助）
- ✅ **容器命名和清理**: 超时时删除容器

#### 修改的函数：
```python
# 新增辅助函数
_check_gpu_available()
_extract_container_name()
_cleanup_docker_container()

# 修改的函数
_build_aizynthfinder_docker_command()  # 添加 GPU 支持和容器命名
_run_command()                          # 添加超时清理
```

---

### 4. **autogrow4_adapter.py**

#### 添加的功能：
- ✅ **容器命名和清理**: 超时时删除容器
- ⚠️ **不需要 GPU**: AutoGrow4 是传统算法，CPU 足够

#### 修改的函数：
```python
# 新增辅助函数
_cleanup_docker_container()

# 修改的函数
_run_autogrow4_docker()          # 添加容器命名和超时清理
```

---

### 5. **测试更新** (test_docking_adapters.py)

#### 新增测试：
- ✅ `test_gnina_docker_includes_gpu_flag_when_available` - 验证 GPU 标志
- ✅ `test_gnina_cpu_mode_disables_cnn_scoring` - 验证 CPU 模式参数
- ✅ `test_timeout_cleanup_removes_docker_container` - 验证容器清理

#### 修改测试：
- ✅ 所有测试添加 GPU 检测 mock，确保在测试环境中可预测

---

## 使用说明

### GPU 配置（如果有 GPU）

1. **安装 NVIDIA Docker 支持**:
```bash
# Windows (WSL2) 或 Linux
# 参考: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

# 验证 GPU 可用
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

2. **代码会自动检测**: 
   - 如果 GPU 可用 → 自动使用 `--gpus all`
   - 如果 GPU 不可用 → 自动使用 CPU 友好参数

### CPU 模式（无 GPU）

**gnina CPU 优化**:
- 自动添加 `--cnn_scoring none` 禁用 CNN（最快）
- 可选：在 `DockingToolRequest` 中设置较小的 `exhaustiveness` (4-6 而不是 8)

---

## 性能改进

### 预期效果

#### 有 GPU：
- gnina: **10-100x 加速** (5分钟 → 5-30秒)
- diffdock: **10-50x 加速**
- chemprop: **5-20x 加速**

#### 无 GPU (CPU 模式)：
- gnina: **5-10x 加速** (5分钟 → 30-60秒，禁用 CNN)
- 其他工具: CPU 模式本身就很快

#### 容器清理：
- **消除恶性循环**: 不再积累残留容器
- **稳定性能**: 每次对接性能一致，不会越来越慢

---

## 验证方法

### 1. 检查残留容器
```bash
# 运行前
docker ps -a | grep -E "gnina|vina|diffdock|chemprop|aizynthfinder"

# 运行对接任务...

# 运行后 - 应该只有 --rm 容器，没有残留
docker ps -a | grep -E "gnina|vina|diffdock|chemprop|aizynthfinder"
```

### 2. 检查 GPU 是否被使用
```bash
# 运行对接时，另一个终端执行
nvidia-smi

# 应该看到 Docker 进程在使用 GPU
```

### 3. 运行测试
```bash
pytest tests/test_docking_adapters.py -v
# 所有 13 个测试应该通过
```

---

## 工具 GPU 需求总结

| 工具 | GPU 需求 | 原因 | CPU 模式可用 |
|------|---------|------|-------------|
| **gnina** | ✅ **强烈需要** | CNN scoring 在 CPU 上极慢 | ✅ (禁用 CNN) |
| **diffdock** | ✅ **强烈需要** | 深度学习 diffusion model | ⚠️ (非常慢) |
| **chemprop** | ✅ **需要** | 神经网络 ADMET 预测 | ✅ (可接受) |
| **aizynthfinder** | ⚠️ **可选** | 深度学习逆合成 | ✅ (可接受) |
| **vina** | ❌ **不需要** | 传统算法 | ✅ (推荐) |
| **autogrow4** | ❌ **不需要** | 遗传算法 | ✅ (推荐) |

---

## 清理现有残留容器

**首次运行前，清理所有旧的残留容器**:

```bash
# Windows PowerShell
docker ps -a --filter "ancestor=gnina/gnina" --format "{{.ID}}" | ForEach-Object { docker rm -f $_ }
docker ps -a --filter "ancestor=diffdock" --format "{{.ID}}" | ForEach-Object { docker rm -f $_ }
docker ps -a --filter "ancestor=chemprop" --format "{{.ID}}" | ForEach-Object { docker rm -f $_ }

# Linux/macOS
docker ps -a | grep -E "gnina|vina|diffdock|chemprop|aizynthfinder" | awk '{print $1}' | xargs -r docker rm -f
```

---

## 相关文件

### 修改的文件
- `src/medagent/services/docking_adapters.py`
- `src/medagent/services/admet_adapter.py`
- `src/medagent/services/aizynthfinder_adapter.py`
- `src/medagent/services/autogrow4_adapter.py`
- `tests/test_docking_adapters.py`

### 参考文档
- [gnina README](https://github.com/gnina/gnina)
- [AutoDock Vina Documentation](https://autodock-vina.readthedocs.io/)
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/)
- [Docker GPU support](https://docs.docker.com/engine/containers/gpu/)

---

## 测试结果

```
============================= test session starts ==============================
tests/test_docking_adapters.py::test_parse_vina_output_reads_best_affinity_from_table PASSED
tests/test_docking_adapters.py::test_parse_gnina_output_reads_affinity_and_cnn_scores PASSED
tests/test_docking_adapters.py::test_parse_gnina_output_does_not_read_cnn_affinity_as_affinity PASSED
tests/test_docking_adapters.py::test_parse_gnina_output_ignores_implausible_affinity_values PASSED
tests/test_docking_adapters.py::test_gnina_command_uses_receptor_ligand_grid_and_output PASSED
tests/test_docking_adapters.py::test_external_docking_prefers_gnina_and_parses_success PASSED
tests/test_docking_adapters.py::test_external_docking_uses_vina_for_prepared_pdbqt_inputs PASSED
tests/test_docking_adapters.py::test_external_docking_runs_gnina_from_docker_image PASSED
tests/test_docking_adapters.py::test_gnina_status_detects_docker_image_when_binary_is_missing PASSED
tests/test_docking_adapters.py::test_vina_docker_command_uses_python_vina_package_with_pdbqt_inputs PASSED
tests/test_docking_adapters.py::test_gnina_docker_includes_gpu_flag_when_available PASSED
tests/test_docking_adapters.py::test_gnina_cpu_mode_disables_cnn_scoring PASSED
tests/test_docking_adapters.py::test_timeout_cleanup_removes_docker_container PASSED

============================== 13 passed in 0.22s
```

✅ **所有测试通过！**
