from pathlib import Path

import pytest

from medagent.core.config import Settings
from medagent.db.models import Base, DockingResult, Molecule, Project
from medagent.db.session import build_engine, build_session_factory
from medagent.services.docking_adapters import DockingToolResult
from medagent.services.docking_workflow import (
    LigandPreparationResult,
    ReceptorPreparationResult,
    _convert_to_pdbqt,
    run_docking_workflow,
)
from medagent.services.pdbqt_validation import is_valid_vina_ligand_pdbqt


def test_convert_ligand_to_vina_pdbqt_with_meeko(tmp_path):
    pytest.importorskip("meeko")
    chem = pytest.importorskip("rdkit.Chem")
    all_chem = pytest.importorskip("rdkit.Chem.AllChem")

    mol = chem.AddHs(chem.MolFromSmiles("CCO"))
    assert all_chem.EmbedMolecule(mol, randomSeed=42) == 0
    sdf_file = tmp_path / "ligand.sdf"
    writer = chem.SDWriter(str(sdf_file))
    writer.write(mol)
    writer.close()

    output = _convert_to_pdbqt(sdf_file, is_ligand=True)

    assert output == Path(tmp_path / "ligand.pdbqt")
    assert is_valid_vina_ligand_pdbqt(output)


def test_docking_workflow_persists_result_with_current_database_schema(tmp_path, monkeypatch):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'workflow.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)

    monkeypatch.setattr(
        "medagent.services.docking_workflow.prepare_ligand_from_smiles",
        lambda **kwargs: LigandPreparationResult(
            success=True,
            ligand_file=str(tmp_path / "ligand.sdf"),
            format="sdf",
            conformers_generated=1,
            energy=-1.2,
        ),
    )
    monkeypatch.setattr(
        "medagent.services.docking_workflow.prepare_receptor_from_pdb",
        lambda **kwargs: ReceptorPreparationResult(
            success=True,
            receptor_file=str(tmp_path / "receptor.pdb"),
            format="pdb",
            chains_kept=["A"],
            hydrogens_added=True,
        ),
    )
    monkeypatch.setattr(
        "medagent.services.docking_workflow.run_external_docking",
        lambda request, tool_status: DockingToolResult(
            adapter_mode="diffdock_docker_docking",
            tool_name="diffdock",
            success=True,
            diffdock_confidence=1.1,
            pose_file=str(tmp_path / "pose.sdf"),
            labels=["external_docking_adapter_used", "diffdock_adapter"],
        ),
    )

    with session_factory() as db:
        project = Project(project_id="PROJ-DOCK", name="Docking")
        molecule = Molecule(
            molecule_id="MOL-DOCK",
            project_id=project.project_id,
            smiles="CCO",
        )
        db.add_all([project, molecule])
        db.commit()

        result = run_docking_workflow(
            db,
            project,
            molecule,
            receptor_pdb_file=str(tmp_path / "receptor.pdb"),
            binding_site_center=[1.0, 2.0, 3.0],
            binding_site_size=[18.0, 18.0, 18.0],
            tool_status={"diffdock": {"available": True}},
        )

        persisted = db.query(DockingResult).filter_by(molecule_id=molecule.molecule_id).one()
        assert result.success is True
        assert result.docking_result_id == persisted.id
        assert result.cnn_score is None
        assert result.diffdock_confidence == 1.1
        assert persisted.cnn_score is None
        assert persisted.diffdock_confidence == 1.1
        assert persisted.raw_output["tool_name"] == "diffdock"
