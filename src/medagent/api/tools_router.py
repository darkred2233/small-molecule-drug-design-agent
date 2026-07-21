"""
计算化学工具API路由

提供统一的工具调用接口：
- /tools/status - 检查所有工具状态
- /tools/rdkit/validate - RDKit分子验证和描述符
- /tools/admet/predict - ADMET预测
- /tools/docking/run - 分子对接
- /tools/generation/run - 分子生成
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from medagent.services.admet_adapter import (
    ChempropADMETRequest,
    check_chemprop_available,
    run_chemprop_admet,
)
from medagent.services.aizynthfinder_adapter import aizynthfinder_tool_status
from medagent.services.autogrow4_adapter import autogrow4_tool_status
from medagent.services.docking_adapters import (
    DockingToolRequest,
    check_gnina_available,
    check_vina_available,
    run_external_docking,
)
from medagent.services.rdkit_enhanced import validate_and_calculate_enhanced
from medagent.services.reinvent4_adapter import reinvent4_tool_status


router = APIRouter(prefix="/tools", tags=["计算工具"])


# ============================================================================
# 请求/响应模型
# ============================================================================

class ToolStatusResponse(BaseModel):
    """Availability of the supported compute tools."""
    rdkit: dict[str, Any] = Field(description="RDKit状态")
    chemprop: dict[str, Any] = Field(description="Chemprop状态")
    gnina: dict[str, Any] = Field(description="GNINA状态")
    vina: dict[str, Any] = Field(description="Vina状态")
    reinvent4: dict[str, Any] = Field(description="REINVENT4状态")
    autogrow4: dict[str, Any] = Field(description="AutoGrow4状态")
    aizynthfinder: dict[str, Any] = Field(description="AiZynthFinder状态")
    summary: dict[str, Any] = Field(description="汇总信息")


class RDKitValidateRequest(BaseModel):
    """RDKit验证请求"""
    smiles: str = Field(description="SMILES字符串")
    calculate_descriptors: bool = Field(default=True, description="是否计算描述符")
    check_alerts: bool = Field(default=True, description="是否检查结构警报")


class RDKitValidateResponse(BaseModel):
    """RDKit验证响应"""
    available: bool = Field(description="RDKit是否可用")
    valid: bool = Field(description="分子是否有效")
    labels: list[str] = Field(description="标签列表")
    reason: str | None = Field(description="失败原因")
    descriptors: dict[str, Any] | None = Field(description="分子描述符")
    structural_alerts: list[dict[str, Any]] = Field(default_factory=list, description="结构警报")
    warnings: list[str] = Field(default_factory=list, description="警告信息")
    drug_likeness_score: dict[str, Any] | None = Field(description="药物相似性评分")


class ADMETPredictRequest(BaseModel):
    """ADMET预测请求"""
    smiles_list: list[str] = Field(description="SMILES列表")
    molecule_ids: list[str] = Field(description="分子ID列表")
    properties: list[str] = Field(
        default_factory=lambda: [
            "hERG", "Ames", "CYP3A4", "CYP2D6",
            "solubility", "permeability", "DILI", "Pgp", "BBB"
        ],
        description="预测性质列表"
    )
    use_docker: bool = Field(default=False, description="是否使用Docker")
    timeout_seconds: int = Field(default=300, description="超时时间（秒）")


class ADMETPredictResponse(BaseModel):
    """ADMET预测响应"""
    adapter_mode: str = Field(description="适配器模式")
    tool_name: str = Field(description="工具名称")
    success: bool = Field(description="是否成功")
    results: list[dict[str, Any]] = Field(default_factory=list, description="预测结果")
    labels: list[str] = Field(default_factory=list, description="标签")
    warnings: list[str] = Field(default_factory=list, description="警告")
    runtime_seconds: float = Field(description="运行时间")


class DockingRunRequest(BaseModel):
    """对接运行请求"""
    receptor_file: str = Field(description="受体文件路径")
    ligand_file: str = Field(description="配体文件路径")
    output_dir: str = Field(description="输出目录")
    grid_center: list[float] | None = Field(None, description="网格中心 [x,y,z]")
    grid_size: list[float] | None = Field(None, description="网格大小 [x,y,z]")
    exhaustiveness: int = Field(default=8, description="搜索精度")
    timeout_seconds: int = Field(default=900, description="超时时间（秒）")
    molecule_id: str | None = Field(None, description="分子ID")


class DockingRunResponse(BaseModel):
    """对接运行响应"""
    adapter_mode: str = Field(description="适配器模式")
    tool_name: str = Field(description="工具名称")
    success: bool = Field(description="是否成功")
    vina_score: float | None = Field(None, description="Vina评分")
    cnn_score: float | None = Field(None, description="CNN评分")
    cnn_affinity: float | None = Field(None, description="CNN亲和力")
    pose_file: str | None = Field(None, description="姿态文件路径")
    labels: list[str] = Field(default_factory=list, description="标签")
    warnings: list[str] = Field(default_factory=list, description="警告")
    runtime_seconds: float = Field(description="运行时间")


# ============================================================================
# API端点
# ============================================================================

@router.get("/status", response_model=ToolStatusResponse, summary="检查工具状态")
async def get_tools_status():
    """
    检查所有计算化学工具的可用性状态

    返回每个工具的：
    - 是否可用
    - 安装模式（python包/CLI/Docker）
    - 版本信息
    - 路径或镜像名
    """
    # 检查RDKit
    rdkit_status = _check_rdkit_status()

    # 检查Chemprop
    chemprop_status = check_chemprop_available()

    gnina_status = check_gnina_available()
    vina_status = check_vina_available()

    # 检查生成工具
    reinvent4_status = reinvent4_tool_status()
    autogrow4_status = autogrow4_tool_status()
    aizynthfinder_status = aizynthfinder_tool_status()

    # 汇总
    available_count = sum([
        rdkit_status.get("available", False),
        chemprop_status.get("available", False),
        gnina_status.get("available", False),
        vina_status.get("available", False),
        reinvent4_status.get("available", False),
        autogrow4_status.get("available", False),
        aizynthfinder_status.get("available", False),
    ])

    return ToolStatusResponse(
        rdkit=rdkit_status,
        chemprop=chemprop_status,
        gnina=gnina_status,
        vina=vina_status,
        reinvent4=reinvent4_status,
        autogrow4=autogrow4_status,
        aizynthfinder=aizynthfinder_status,
        summary={
            "total_tools": 7,
            "available_tools": available_count,
            "critical_missing": [] if rdkit_status.get("available") else ["RDKit"],
        }
    )


@router.post("/rdkit/validate", response_model=RDKitValidateResponse, summary="RDKit分子验证")
async def validate_molecule(request: RDKitValidateRequest):
    """
    使用RDKit验证分子并计算描述符

    功能：
    - SMILES有效性检查
    - 分子标准化
    - 完整描述符计算（MW, LogP, TPSA, QED, SA Score等）
    - Lipinski五规则检查
    - 结构警报检测（PAINS/Brenk/NIH）
    - 药物相似性综合评分
    """
    result = validate_and_calculate_enhanced(request.smiles)

    response_data = {
        "available": result.available,
        "valid": result.valid,
        "labels": result.labels,
        "reason": result.reason,
        "warnings": result.warnings,
        "descriptors": None,
        "structural_alerts": [],
        "drug_likeness_score": None,
    }

    if result.descriptors:
        from medagent.services.rdkit_enhanced import calculate_drug_likeness_score
        from dataclasses import asdict

        descriptors_dict = asdict(result.descriptors)
        response_data["descriptors"] = descriptors_dict

        # 计算药物相似性评分
        if request.calculate_descriptors:
            drug_score = calculate_drug_likeness_score(result.descriptors)
            response_data["drug_likeness_score"] = drug_score

    if result.structural_alerts and request.check_alerts:
        from dataclasses import asdict
        response_data["structural_alerts"] = [
            asdict(alert) for alert in result.structural_alerts
        ]

    return RDKitValidateResponse(**response_data)


@router.post("/admet/predict", response_model=ADMETPredictResponse, summary="ADMET预测")
async def predict_admet(request: ADMETPredictRequest):
    """
    使用Chemprop预测ADMET性质

    支持预测：
    - hERG心脏毒性
    - Ames致突变性
    - CYP3A4/CYP2D6抑制
    - 溶解度
    - 渗透性
    - DILI肝毒性
    - Pgp底物
    - BBB穿透

    如果Chemprop不可用，会返回错误提示使用RDKit代理
    """
    if len(request.smiles_list) != len(request.molecule_ids):
        raise HTTPException(
            status_code=400,
            detail="smiles_list和molecule_ids长度必须相同"
        )

    chemprop_request = ChempropADMETRequest(
        smiles_list=request.smiles_list,
        molecule_ids=request.molecule_ids,
        properties=request.properties,
        use_docker=request.use_docker,
        timeout_seconds=request.timeout_seconds,
    )

    result = run_chemprop_admet(chemprop_request)

    # 转换结果为字典
    from dataclasses import asdict
    results_dict = [asdict(r) for r in result.results]

    return ADMETPredictResponse(
        adapter_mode=result.adapter_mode,
        tool_name=result.tool_name,
        success=result.success,
        results=results_dict,
        labels=result.labels,
        warnings=result.warnings,
        runtime_seconds=result.runtime_seconds,
    )


@router.post("/docking/run", response_model=DockingRunResponse, summary="分子对接")
async def run_docking(request: DockingRunRequest):
    """
    运行分子对接

    支持的工具（按优先级）：
    1. GNINA（推荐）- 带CNN评分
    2. AutoDock Vina - 标准对接

    系统会自动选择第一个可用的工具
    """
    tool_status = {
        "gnina": check_gnina_available(),
        "vina": check_vina_available(),
    }

    # 创建对接请求
    docking_request = DockingToolRequest(
        receptor_file=request.receptor_file,
        ligand_file=request.ligand_file,
        output_dir=request.output_dir,
        grid_center=request.grid_center,
        grid_size=request.grid_size,
        exhaustiveness=request.exhaustiveness,
        timeout_seconds=request.timeout_seconds,
        molecule_id=request.molecule_id,
    )

    # 运行对接
    result = run_external_docking(docking_request, tool_status)

    if result is None:
        raise HTTPException(
            status_code=503,
            detail="没有可用的对接工具。请安装GNINA或Vina。"
        )

    from dataclasses import asdict
    result_dict = asdict(result)

    return DockingRunResponse(**result_dict)


# ============================================================================
# 辅助函数
# ============================================================================

def _check_rdkit_status() -> dict[str, Any]:
    """检查RDKit状态"""
    try:
        from rdkit import __version__
        return {
            "available": True,
            "version": __version__,
            "mode": "python_package",
        }
    except ImportError:
        return {
            "available": False,
            "version": None,
            "mode": None,
        }


def _check_tool_cli(command: str, version_arg: str) -> dict[str, Any]:
    """检查命令行工具"""
    import subprocess

    result = {
        "available": False,
        "version": None,
        "path": None,
    }

    try:
        proc = subprocess.run(
            [command, version_arg],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 or proc.stdout:
            result["available"] = True
            result["version"] = proc.stdout.strip()
            result["path"] = command
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return result


def _check_tool_docker(image_name: str) -> dict[str, Any]:
    """检查Docker镜像"""
    import subprocess

    result = {
        "available": False,
        "mode": None,
        "docker_image": None,
    }

    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", image_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            result["available"] = True
            result["mode"] = "docker"
            result["docker_image"] = image_name
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return result
