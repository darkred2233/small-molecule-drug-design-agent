# 🎯 Docker工具安装 - 就绪执行

## ✅ 已为你准备好的文件

### 自动安装脚本（3个）

1. **`scripts/build_docker_tools.bat`** ⭐ 推荐
   - 双击即可运行
   - 自动构建所有工具
   - 显示详细进度

2. **`scripts/build_docker_tools.ps1`**
   - PowerShell版本
   - 彩色输出
   - 更详细的日志

3. **`DOCKER_INSTALLATION_GUIDE.md`**
   - 完整安装指南
   - 分步说明
   - 故障排除

---

## 🚀 立即执行（3步）

### 第1步：确保Docker Desktop运行
打开Docker Desktop应用程序，确保它在运行。

### 第2步：运行构建脚本
**方法A（推荐）：**
```
双击文件：scripts\build_docker_tools.bat
```

**方法B：**
```powershell
cd C:\Users\zhihong\Desktop\small-molecule-drug-design-agent
.\scripts\build_docker_tools.ps1
```

**方法C：**
```bash
cd C:\Users\zhihong\Desktop\small-molecule-drug-design-agent

# 手动逐个构建
docker pull gnina/gnina:latest
docker compose build chemprop
docker compose build diffdock
docker compose build reinvent4
docker compose build autogrow4
```

### 第3步：验证安装
```bash
python scripts\check_tools.py --verbose
```

---

## ⏱️ 预计时间

| 工具 | 构建时间 | 优先级 |
|------|---------|--------|
| GNINA | 1-2分钟 | ⭐⭐⭐ |
| Chemprop | 5-10分钟 | ⭐⭐⭐ |
| DiffDock | 10-15分钟 | ⭐⭐ |
| REINVENT4 | 3-5分钟 | ⭐⭐ |
| AutoGrow4 | 5-10分钟 | ⭐ |

**总计：约25-45分钟**

---

## 📋 构建流程

脚本会自动执行以下步骤：

```
✅ 检查Docker是否安装
✅ 检查Docker是否运行
✅ 拉取GNINA公共镜像
✅ 构建Chemprop镜像
✅ 构建DiffDock镜像
✅ 构建REINVENT4镜像
✅ 构建AutoGrow4镜像
✅ 显示构建结果
✅ 列出已构建的镜像
```

---

## 🎯 工具用途

### GNINA（分子对接）⭐⭐⭐
- **功能：** 分子与蛋白对接，带CNN评分
- **用途：** 评估分子与靶点的结合能力
- **必需性：** 高（核心对接工具）

### Chemprop（ADMET预测）⭐⭐⭐
- **功能：** 预测ADMET性质（毒性、溶解度等）
- **用途：** 评估分子成药性
- **必需性：** 高（你已部署）

### DiffDock（分子对接）⭐⭐
- **功能：** 基于扩散模型的对接
- **用途：** 无需定义结合位点的对接
- **必需性：** 中（高级对接工具）

### REINVENT4（分子生成）⭐⭐
- **功能：** 基于强化学习的分子生成
- **用途：** 自动生成候选分子
- **必需性：** 中（生成工具）

### AutoGrow4（分子生成）⭐
- **功能：** 基于遗传算法的分子生成
- **用途：** 自动优化分子结构
- **必需性：** 低（备选生成工具）

---

## ✅ 预期输出

构建成功后，你应该看到：

```
========================================
构建完成总结
========================================

总工具数: 5
成功: 5
失败: 0
跳过: 0

已构建的镜像：
gnina/gnina                           latest
small-molecule-drug-design-agent-chemprop    latest
small-molecule-drug-design-agent-diffdock    latest
small-molecule-drug-design-agent-reinvent4   latest
small-molecule-drug-design-agent-autogrow4   latest

🎉 所有工具构建成功！
```

---

## 🧪 测试工具

构建完成后，测试每个工具：

```bash
# 测试所有工具
python scripts\manage_docker_tools.py test

# 测试单个工具
python scripts\manage_docker_tools.py test chemprop
python scripts\manage_docker_tools.py test diffdock

# 测试Chemprop完整流程
python scripts\manage_docker_tools.py test-chemprop
```

---

## 🔧 故障排除

### 问题1：Docker未运行
**错误：** `Cannot connect to the Docker daemon`
**解决：** 启动Docker Desktop应用程序

### 问题2：网络连接问题
**错误：** `failed to fetch`
**解决：** 检查网络连接，或使用VPN

### 问题3：磁盘空间不足
**错误：** `no space left on device`
**解决：** 清理Docker：`docker system prune -a`

### 问题4：构建失败
**解决：** 重新构建单个工具
```bash
docker compose build --no-cache chemprop
```

---

## 📊 磁盘空间需求

| 工具 | 镜像大小 |
|------|---------|
| GNINA | ~2GB |
| Chemprop | ~3GB |
| DiffDock | ~5GB |
| REINVENT4 | ~2GB |
| AutoGrow4 | ~3GB |

**总计：约15-20GB**

建议预留30GB空间以确保构建顺利。

---

## 🎊 下一步操作

构建完成后：

1. **验证安装**
   ```bash
   python scripts\check_tools.py --verbose
   ```

2. **查看工具状态**
   ```bash
   python scripts\manage_docker_tools.py status
   ```

3. **启动服务**
   ```bash
   docker compose up -d chemprop
   ```

4. **运行测试**
   ```bash
   pytest tests\test_tools_integration.py -v
   ```

5. **开始使用！**
   查看 `FINAL_DELIVERY_REPORT.md` 了解如何使用这些工具

---

## 📚 相关文档

- `DOCKER_INSTALLATION_GUIDE.md` - 详细安装指南
- `FINAL_DELIVERY_REPORT.md` - 完整功能说明
- `TOOLS_QUICKSTART.md` - 快速参考
- `docs/CORE_TOOLS_COMPLETION.md` - 核心功能文档

---

## ✨ 准备就绪！

所有准备工作已完成，现在只需：

### 👉 双击运行：`scripts\build_docker_tools.bat`

然后等待25-45分钟，完成后所有工具就可以使用了！

---

**祝你构建顺利！如有问题，请查看 `DOCKER_INSTALLATION_GUIDE.md`** 🚀
