# API payload 使用提示

所有路径都按项目根目录相对路径填写。建议先运行：

```powershell
curl.exe http://127.0.0.1:8001/tools/status
```

直接跑 RDKit 验证：

```powershell
curl.exe -X POST http://127.0.0.1:8001/tools/rdkit/validate -H "Content-Type: application/json" -d "{\"smiles\":\"O=C(NCCO)c1ccccc1\",\"calculate_descriptors\":true,\"check_alerts\":true}"
```

候选评估：

```powershell
curl.exe -X POST http://127.0.0.1:8001/projects/PROJ-8A2756E8CB/candidate-assessment/run -H "Content-Type: application/json" --data-binary "@student_tool_runs/student_A_docking_assessment/candidate_assessment_external_top5_payload.json"
```

如果 Docker 没开，外部对接、DiffDock、AiZynthFinder 可能不可用，结果会退回 surrogate 或出现外部工具不可用提示。这个现象可以作为实验记录的一部分。

