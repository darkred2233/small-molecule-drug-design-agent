# 📑 项目文件索引

快速查找所有新增文件和文档

---

## 🔧 核心工作流模块

| 文件 | 功能 | 行数 |
|------|------|------|
| `src/medagent/services/docking_workflow.py` | 完整分子对接工作流 | 550 |
| `src/medagent/services/admet_workflow.py` | 完整ADMET预测工作流 | 450 |
| `src/medagent/services/synthesis_workflow.py` | 合成可及性评估 | 520 |

**用途：** 端到端的分子评估流程

---

## 🧪 增强功能模块

| 文件 | 功能 | 行数 |
|------|------|------|
| `src/medagent/services/rdkit_enhanced.py` | 增强RDKit化学计算 | 410 |
| `src/medagent/services/docking_adapters.py` | 对接工具适配器 | 544 |
| `src/medagent/services/admet_adapter.py` | Chemprop ADMET适配器 | 530 |
| `src/medagent/api/tools_router.py` | RESTful API端点 | 380 |

**用途：** 底层工具集成和API接口

---

## 🛠️ 管理和测试脚本

| 文件 | 功能 | 行数 |
|------|------|------|
| `scripts/check_tools.py` | 工具状态检测 | 468 |
| `scripts/manage_docker_tools.py` | Docker工具管理 | 608 |
| `tests/test_tools_integration.py` | 集成测试 | 450 |

**用途：** 工具管理、测试和诊断

---

## 📚 文档文件

### 快速参考
| 文件 | 用途 |
|------|------|
| `TOOLS_QUICKSTART.md` | 快速参考卡片 |
| `FINAL_DELIVERY_REPORT.md` | 最终交付报告 |
| `DELIVERY_CHECKLIST.md` | 第一阶段交付清单 |

### 详细文档
| 文件 | 用途 |
|------|------|
| `docs/TOOLS_INSTALLATION.md` | 详细安装指南 |
| `docs/TOOLS_COMPLETION_SUMMARY.md` | 第一阶段工作总结 |
| `docs/CORE_TOOLS_COMPLETION.md` | 核心工具完成总结 |
| `docs/COMPUTE_TOOLS_INTEGRATION_SUMMARY.md` | 工具集成总结 |

### 技术文档
| 文件 | 用途 |
|------|------|
| `docs/CHEMPROP_ADAPTER_BUILD.md` | Chemprop集成说明 |
| `docs/DIFFDOCK_ADAPTER_BUILD.md` | DiffDock集成说明 |
| `docs/REINVENT4_ADAPTER_BUILD.md` | REINVENT4集成说明 |
| `docs/AUTOGROW4_ADAPTER_BUILD.md` | AutoGrow4集成说明 |

---

## 🎯 快速导航

### 想要...

**检查工具状态？**
→ `python scripts/check_tools.py --verbose`

**查看快速参考？**
→ 查看 `TOOLS_QUICKSTART.md`

**查看完整交付报告？**
→ 查看 `FINAL_DELIVERY_REPORT.md`

**了解如何安装工具？**
→ 查看 `docs/TOOLS_INSTALLATION.md`

**使用RDKit增强功能？**
→ 查看 `src/medagent/services/rdkit_enhanced.py`

**运行分子对接？**
→ 查看 `src/medagent/services/docking_workflow.py`

**运行ADMET预测？**
→ 查看 `src/medagent/services/admet_workflow.py`

**评估合成可及性？**
→ 查看 `src/medagent/services/synthesis_workflow.py`

**管理Docker工具？**
→ `python scripts/manage_docker_tools.py status`

**运行测试？**
→ `pytest tests/test_tools_integration.py -v`

---

## 📊 按功能分类

### 分子验证和描述符
- `src/medagent/services/rdkit_enhanced.py`
- 测试: `tests/test_tools_integration.py::TestRDKitEnhanced`

### 分子对接
- `src/medagent/services/docking_workflow.py`
- `src/medagent/services/docking_adapters.py`
- 测试: `tests/test_tools_integration.py::TestDockingAdapters`

### ADMET预测
- `src/medagent/services/admet_workflow.py`
- `src/medagent/services/admet_adapter.py`
- 测试: `tests/test_tools_integration.py::TestChempropAdapter`

### 合成评估
- `src/medagent/services/synthesis_workflow.py`

### API接口
- `src/medagent/api/tools_router.py`
- 测试: `tests/test_tools_integration.py::TestToolsAPI`

---

## 🔍 常见问题快速查找

| 问题 | 查看文件 |
|------|---------|
| 如何安装RDKit？ | `docs/TOOLS_INSTALLATION.md` |
| 如何使用Docker部署？ | `scripts/manage_docker_tools.py` |
| Chemprop如何工作？ | `docs/CHEMPROP_ADAPTER_BUILD.md` |
| 如何计算SA Score？ | `src/medagent/services/synthesis_workflow.py` |
| 如何添加新的对接工具？ | `src/medagent/services/docking_adapters.py` |
| 测试失败怎么办？ | `docs/TOOLS_INSTALLATION.md` |

---

## 📝 开发指南

### 添加新功能
1. 查看相关模块的代码
2. 参考现有的工作流模式
3. 添加相应的测试用例
4. 更新文档

### 调试问题
1. 运行 `python scripts/check_tools.py --verbose`
2. 检查工具可用性
3. 运行相关测试
4. 查看错误日志

---

## 统计信息

- **新增文件总数:** 16个
- **代码文件:** 10个
- **测试文件:** 1个
- **文档文件:** 5个
- **总代码行数:** ~5000行
- **总文档行数:** ~1000行
- **测试用例数:** 16个

---

**最后更新:** 2026-07-11
