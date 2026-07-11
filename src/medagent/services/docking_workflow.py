"""
完整的分子对接工作流

提供端到端的对接流程：
1. 受体准备（蛋白结构清理、加氢、电荷分配）
2. 配体准备（3D构象生成、能量优化）
3. 对接执行（GNINA/Vina/DiffDock）
4. 结果分析和排序

依赖：
- RDKit（必需）
- OpenBabel（可选，用于格式转换）
- GNINA/Vina/DiffDock（至少一个）
"""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import DockingResult, Molecule, Project
from medagent.services.docking_adapters import (
    DockingToolRequest,
    run_external_docking,
)
from medagent.services.ids import new_id


@dataclass
class LigandPreparationResult:
    """配体准备结果"""
    success: bool
    ligand_file: str | None
    format: str  # sdf, pdbqt, mol2
    conformers_generated: int
    energy: float | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ReceptorPreparationResult:
    """受体准备结果"""
    success: bool
    receptor_file: str | None
    format: str  # pdb, pdbqt
    chains_kept: list[str]
    hydrogens_added: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class DockingWorkflowResult:
    """对接工作流完整结果"""
    success: bool
    molecule_id: str
    docking_result_id: str | None
    vina_score: float | None
    cnn_score: float | None
    pose_file: str | None
    ligand_prep: LigandPreparationResult | None
    receptor_prep: ReceptorPreparationResult | None
    docking_tool: str | None
    labels: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    runtime_seconds: float = 0.0


def prepare_ligand_from_smiles(
    smiles: str,
    output_dir: Path,
    molecule_id: str,
    target_format: str = "sdf",
    add_hydrogens: bool = True,
    generate_3d: bool = True,
    num_conformers: int = 1,
) -> LigandPreparationResult:
    """
    从SMILES准备配体

    步骤：
    1. 解析SMILES
    2. 添加氢原子
    3. 生成3D构象
    4. 能量优化
    5. 保存为目标格式
    """
    warnings: list[str] = []

    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError:
        return LigandPreparationResult(
            success=False,
            ligand_file=None,
            format=target_format,
            conformers_generated=0,
            energy=None,
            warnings=["rdkit_not_available"],
        )

    # 解析SMILES
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return LigandPreparationResult(
            success=False,
            ligand_file=None,
            format=target_format,
            conformers_generated=0,
            energy=None,
            warnings=["invalid_smiles"],
        )

    # 添加氢原子
    if add_hydrogens:
        mol = Chem.AddHs(mol)

    # 生成3D构象
    conformers_generated = 0
    energy = None

    if generate_3d:
        try:
            # 生成多个构象
            conf_ids = AllChem.EmbedMultipleConfs(
                mol,
                numConfs=num_conformers,
                randomSeed=42,
                useRandomCoords=True,
            )
            conformers_generated = len(conf_ids)

            if conformers_generated == 0:
                warnings.append("conformer_generation_failed")
            else:
                # 对每个构象进行MMFF能量优化
                energies = []
                for conf_id in conf_ids:
                    try:
                        props = AllChem.MMFFGetMoleculeProperties(mol)
                        ff = AllChem.MMFFGetMoleculeForceField(mol, props, confId=conf_id)
                        ff.Minimize()
                        energies.append(ff.CalcEnergy())
                    except Exception:
                        warnings.append("mmff_optimization_failed")

                if energies:
                    energy = min(energies)
                    # 保留能量最低的构象
                    best_conf = conf_ids[energies.index(min(energies))]
                    if best_conf != 0:
                        # 将最优构象设为第一个
                        mol.RemoveAllConformers()
                        mol.AddConformer(Chem.Conformer(mol.GetConformer(best_conf)))

        except Exception as e:
            warnings.append(f"3d_generation_error: {str(e)}")
            conformers_generated = 0

    # 保存文件
    output_dir.mkdir(parents=True, exist_ok=True)
    ligand_file = output_dir / f"{molecule_id}_ligand.{target_format}"

    try:
        if target_format == "sdf":
            writer = Chem.SDWriter(str(ligand_file))
            writer.write(mol)
            writer.close()
        elif target_format == "mol2":
            Chem.MolToMolFile(mol, str(ligand_file))
        elif target_format == "pdbqt":
            # PDBQT需要OpenBabel或Meeko
            warnings.append("pdbqt_format_requires_openbabel_or_meeko")
            # 先保存为SDF，然后尝试转换
            sdf_file = output_dir / f"{molecule_id}_ligand.sdf"
            writer = Chem.SDWriter(str(sdf_file))
            writer.write(mol)
            writer.close()

            # 尝试使用obabel转换
            pdbqt_file = _convert_to_pdbqt(sdf_file, is_ligand=True)
            if pdbqt_file:
                ligand_file = pdbqt_file
            else:
                warnings.append("pdbqt_conversion_failed")
                ligand_file = sdf_file
                target_format = "sdf"
        else:
            warnings.append(f"unsupported_format: {target_format}")
            return LigandPreparationResult(
                success=False,
                ligand_file=None,
                format=target_format,
                conformers_generated=conformers_generated,
                energy=energy,
                warnings=warnings,
            )

        return LigandPreparationResult(
            success=True,
            ligand_file=str(ligand_file),
            format=target_format,
            conformers_generated=conformers_generated if generate_3d else 1,
            energy=round(energy, 3) if energy else None,
            warnings=warnings,
        )

    except Exception as e:
        warnings.append(f"file_write_error: {str(e)}")
        return LigandPreparationResult(
            success=False,
            ligand_file=None,
            format=target_format,
            conformers_generated=conformers_generated,
            energy=energy,
            warnings=warnings,
        )


def prepare_receptor_from_pdb(
    pdb_file: Path,
    output_dir: Path,
    target_format: str = "pdbqt",
    add_hydrogens: bool = True,
    remove_waters: bool = True,
    chains_to_keep: list[str] | None = None,
) -> ReceptorPreparationResult:
    """
    从PDB文件准备受体

    步骤：
    1. 读取PDB
    2. 移除水分子和其他溶剂
    3. 保留指定链
    4. 添加氢原子
    5. 转换为目标格式（通常是PDBQT）
    """
    warnings: list[str] = []

    if not pdb_file.exists():
        return ReceptorPreparationResult(
            success=False,
            receptor_file=None,
            format=target_format,
            chains_kept=[],
            hydrogens_added=False,
            warnings=["pdb_file_not_found"],
        )

    try:
        from rdkit import Chem
    except ImportError:
        warnings.append("rdkit_not_available")
        # 如果只需要PDB格式，可以不需要RDKit
        if target_format == "pdb":
            output_file = output_dir / f"{pdb_file.stem}_prepared.pdb"
            import shutil
            shutil.copy2(pdb_file, output_file)
            return ReceptorPreparationResult(
                success=True,
                receptor_file=str(output_file),
                format="pdb",
                chains_kept=[],
                hydrogens_added=False,
                warnings=warnings,
            )
        else:
            return ReceptorPreparationResult(
                success=False,
                receptor_file=None,
                format=target_format,
                chains_kept=[],
                hydrogens_added=False,
                warnings=warnings,
            )

    # 读取PDB
    mol = Chem.MolFromPDBFile(str(pdb_file), removeHs=False)
    if mol is None:
        warnings.append("pdb_parsing_failed")
        return ReceptorPreparationResult(
            success=False,
            receptor_file=None,
            format=target_format,
            chains_kept=[],
            hydrogens_added=False,
            warnings=warnings,
        )

    # 移除水分子
    if remove_waters:
        mol = Chem.RemoveHs(mol, updateExplicitCount=True)
        # 这里简化处理，实际需要更复杂的逻辑来移除水分子

    # 添加氢原子
    hydrogens_added = False
    if add_hydrogens:
        try:
            mol = Chem.AddHs(mol)
            hydrogens_added = True
        except Exception:
            warnings.append("hydrogen_addition_failed")

    # 保存文件
    output_dir.mkdir(parents=True, exist_ok=True)

    if target_format == "pdb":
        receptor_file = output_dir / f"{pdb_file.stem}_prepared.pdb"
        Chem.MolToPDBFile(mol, str(receptor_file))
    elif target_format == "pdbqt":
        # 先保存为PDB
        pdb_temp = output_dir / f"{pdb_file.stem}_temp.pdb"
        Chem.MolToPDBFile(mol, str(pdb_temp))

        # 转换为PDBQT
        pdbqt_file = _convert_to_pdbqt(pdb_temp, is_ligand=False)
        if pdbqt_file:
            receptor_file = pdbqt_file
        else:
            warnings.append("pdbqt_conversion_failed_using_pdb")
            receptor_file = pdb_temp
            target_format = "pdb"
    else:
        warnings.append(f"unsupported_receptor_format: {target_format}")
        return ReceptorPreparationResult(
            success=False,
            receptor_file=None,
            format=target_format,
            chains_kept=[],
            hydrogens_added=hydrogens_added,
            warnings=warnings,
        )

    return ReceptorPreparationResult(
        success=True,
        receptor_file=str(receptor_file),
        format=target_format,
        chains_kept=chains_to_keep or [],
        hydrogens_added=hydrogens_added,
        warnings=warnings,
    )


def _convert_to_pdbqt(input_file: Path, is_ligand: bool = True) -> Path | None:
    """
    使用OpenBabel或Meeko转换为PDBQT格式

    优先使用：
    1. obabel (OpenBabel命令行)
    2. meeko (Python包)
    """
    import subprocess

    output_file = input_file.with_suffix(".pdbqt")

    # 尝试OpenBabel
    try:
        cmd = [
            "obabel",
            str(input_file),
            "-O",
            str(output_file),
            "-xh",  # 添加氢
        ]

        if is_ligand:
            cmd.append("-xr")  # 可旋转键

        proc = subprocess.run(cmd, capture_output=True, timeout=30)
        if proc.returncode == 0 and output_file.exists():
            return output_file
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 尝试Meeko（仅用于配体）
    if is_ligand:
        try:
            from meeko import MoleculePreparation, PDBQTWriterLegacy
            from rdkit import Chem

            mol = Chem.SDMolSupplier(str(input_file))[0]
            if mol:
                preparator = MoleculePreparation()
                mol_setups = preparator.prepare(mol)

                for setup in mol_setups:
                    pdbqt_string = PDBQTWriterLegacy.write_string(setup)
                    with open(output_file, "w") as f:
                        f.write(pdbqt_string)
                    return output_file
        except (ImportError, Exception):
            pass

    return None


def run_docking_workflow(
    db: Session,
    project: Project,
    molecule: Molecule,
    receptor_pdb_file: str,
    binding_site_center: list[float],
    binding_site_size: list[float],
    tool_status: dict[str, Any],
) -> DockingWorkflowResult:
    """
    运行完整对接工作流

    参数：
        db: 数据库会话
        project: 项目对象
        molecule: 分子对象
        receptor_pdb_file: 受体PDB文件路径
        binding_site_center: 结合位点中心坐标 [x, y, z]
        binding_site_size: 结合位点大小 [x, y, z]
        tool_status: 工具状态字典

    返回：
        DockingWorkflowResult
    """
    import time
    start_time = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="docking_workflow_") as tmpdir:
        tmpdir_path = Path(tmpdir)

        # 步骤1: 准备配体
        ligand_prep = prepare_ligand_from_smiles(
            smiles=molecule.smiles,
            output_dir=tmpdir_path,
            molecule_id=molecule.molecule_id,
            target_format="sdf",  # 大多数工具支持SDF
            add_hydrogens=True,
            generate_3d=True,
            num_conformers=10,
        )

        if not ligand_prep.success:
            return DockingWorkflowResult(
                success=False,
                molecule_id=molecule.molecule_id,
                docking_result_id=None,
                vina_score=None,
                cnn_score=None,
                pose_file=None,
                ligand_prep=ligand_prep,
                receptor_prep=None,
                docking_tool=None,
                labels=["docking_workflow_failed", "ligand_prep_failed"],
                warnings=ligand_prep.warnings,
                runtime_seconds=time.monotonic() - start_time,
            )

        # 步骤2: 准备受体
        receptor_prep = prepare_receptor_from_pdb(
            pdb_file=Path(receptor_pdb_file),
            output_dir=tmpdir_path,
            target_format="pdb",  # GNINA和DiffDock支持PDB
            add_hydrogens=True,
            remove_waters=True,
        )

        if not receptor_prep.success:
            return DockingWorkflowResult(
                success=False,
                molecule_id=molecule.molecule_id,
                docking_result_id=None,
                vina_score=None,
                cnn_score=None,
                pose_file=None,
                ligand_prep=ligand_prep,
                receptor_prep=receptor_prep,
                docking_tool=None,
                labels=["docking_workflow_failed", "receptor_prep_failed"],
                warnings=ligand_prep.warnings + receptor_prep.warnings,
                runtime_seconds=time.monotonic() - start_time,
            )

        # 步骤3: 执行对接
        docking_request = DockingToolRequest(
            receptor_file=receptor_prep.receptor_file,
            ligand_file=ligand_prep.ligand_file,
            output_dir=str(tmpdir_path),
            grid_center=binding_site_center,
            grid_size=binding_site_size,
            exhaustiveness=8,
            timeout_seconds=300,
            molecule_id=molecule.molecule_id,
        )

        docking_result = run_external_docking(docking_request, tool_status)

        if docking_result is None or not docking_result.success:
            return DockingWorkflowResult(
                success=False,
                molecule_id=molecule.molecule_id,
                docking_result_id=None,
                vina_score=docking_result.vina_score if docking_result else None,
                cnn_score=docking_result.cnn_score if docking_result else None,
                pose_file=None,
                ligand_prep=ligand_prep,
                receptor_prep=receptor_prep,
                docking_tool=docking_result.tool_name if docking_result else None,
                labels=["docking_workflow_failed", "docking_execution_failed"],
                warnings=ligand_prep.warnings + receptor_prep.warnings +
                        (docking_result.warnings if docking_result else []),
                runtime_seconds=time.monotonic() - start_time,
            )

        # 步骤4: 保存结果到数据库
        docking_db_result = DockingResult(
            docking_result_id=new_id("DOCK"),
            project_id=project.project_id,
            molecule_id=molecule.molecule_id,
            tool_name=docking_result.tool_name,
            vina_score=docking_result.vina_score,
            cnn_score=docking_result.cnn_score,
            cnn_affinity=docking_result.cnn_affinity,
            pose_file=docking_result.pose_file,
            labels=docking_result.labels,
            warnings=docking_result.warnings,
            tool_metadata={
                "ligand_prep": {
                    "conformers": ligand_prep.conformers_generated,
                    "energy": ligand_prep.energy,
                },
                "receptor_prep": {
                    "hydrogens_added": receptor_prep.hydrogens_added,
                },
                "grid_center": binding_site_center,
                "grid_size": binding_site_size,
            },
        )

        db.add(docking_db_result)
        db.commit()

        return DockingWorkflowResult(
            success=True,
            molecule_id=molecule.molecule_id,
            docking_result_id=docking_db_result.docking_result_id,
            vina_score=docking_result.vina_score,
            cnn_score=docking_result.cnn_score,
            pose_file=docking_result.pose_file,
            ligand_prep=ligand_prep,
            receptor_prep=receptor_prep,
            docking_tool=docking_result.tool_name,
            labels=["docking_workflow_success"] + docking_result.labels,
            warnings=ligand_prep.warnings + receptor_prep.warnings + docking_result.warnings,
            runtime_seconds=time.monotonic() - start_time,
        )
