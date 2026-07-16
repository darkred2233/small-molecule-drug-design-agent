# 化学工具实验数据包

这个目录给除 RAG 负责人之外的两位同学使用。数据都来自当前 BRAF 项目 `PROJ-8A2756E8CB`，目标是让他们直接拿项目里的 RDKit、ADMET、GNINA/Vina/DiffDock、AiZynthFinder 相关能力跑一轮小实验

## 目录说明

- `common/`：BRAF 结合口袋、当前 Agent Top10 基线、外部工具基线。
- `data/3OG7_BRAF_receptor.pdb`：BRAF 受体结构文件，来自项目本地缓存。
- `data/ligands/`：5 个已准备好的候选分子 SDF。
- `data/poses/`：5 个已有 GNINA pose SDF，可作为复现实验对照。
- `data/retrosynthesis/`：5 个已有 AiZynthFinder 路线 JSON，可作为合成路线分析对照。
- `student_A_docking_assessment/`：学生 A 的对接/候选细筛数据。
- `student_B_property_synthesis/`：学生 B 的性质、ADMET、合成可行性数据。



BRAF 对接和外部细筛复现。

Top1 类似物的 RDKit 性质、ADMET、合成可行性筛选。

## 最小运行方式

先在项目根目录启动后端服务，然后用这些 payload 调 API：

```powershell
.\.venv\Scripts\python.exe -m uvicorn medagent.api.app:app --reload --port 8001
```

工具状态检查：

```powershell
curl.exe http://127.0.0.1:8001/tools/status
```

候选评估建议优先跑 `fast` 或 `external`，不要让同学默认跑 `full`。`full` 只适合最终验收或小分子数测试。

