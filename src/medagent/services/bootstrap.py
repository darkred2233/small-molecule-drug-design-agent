from sqlalchemy.orm import Session

from medagent.data.builtin_targets import load_builtin_targets
from medagent.db.models import BindingSite, Project, SeedLigand, Target, TargetDrugLibrary
from medagent.services.ids import new_id


def seed_builtin_targets(db: Session) -> None:
    builtin_targets = load_builtin_targets()
    for target_payload in builtin_targets:
        target = db.query(Target).filter_by(target_id=target_payload["target_id"]).one_or_none()
        if target is None:
            target = Target(
                target_id=target_payload["target_id"],
                name=target_payload["name"],
                aliases=target_payload["aliases"],
                uniprot_id=target_payload["uniprot_id"],
                species=target_payload["species"],
                pdb_ids=target_payload["pdb_ids"],
                pocket_summary=target_payload.get("pocket_summary"),
                summary=target_payload["summary"],
            )
            db.add(target)
        else:
            target.name = target_payload["name"]
            target.aliases = target_payload["aliases"]
            target.uniprot_id = target_payload["uniprot_id"]
            target.species = target_payload["species"]
            target.pdb_ids = target_payload["pdb_ids"]
            target.pocket_summary = target_payload.get("pocket_summary")
            target.summary = target_payload["summary"]

        for drug_payload in target_payload["drugs"]:
            exists = (
                db.query(TargetDrugLibrary)
                .filter_by(
                    target_id=target_payload["target_id"],
                    drug_name=drug_payload["drug_name"],
                )
                .one_or_none()
            )
            if exists is None:
                db.add(TargetDrugLibrary(target_id=target_payload["target_id"], **drug_payload))
            else:
                for key, value in drug_payload.items():
                    setattr(exists, key, value)

        for site_payload in target_payload.get("binding_sites", []):
            _upsert_builtin_binding_site(db, target_payload["target_id"], site_payload)
    db.commit()


def seed_project_target_ligands(db: Session, project: Project) -> dict:
    if not project.target_id:
        return {"created_count": 0, "skipped_count": 0, "seed_ligand_ids": []}

    target_drugs = (
        db.query(TargetDrugLibrary)
        .filter_by(target_id=project.target_id)
        .order_by(TargetDrugLibrary.id.asc())
        .all()
    )
    created_ids: list[str] = []
    skipped_count = 0
    for drug in target_drugs:
        smiles = drug.smiles or drug.canonical_smiles or drug.isomeric_smiles
        if not smiles:
            skipped_count += 1
            continue
        exists = (
            db.query(SeedLigand)
            .filter_by(project_id=project.project_id, name=drug.drug_name)
            .one_or_none()
        )
        if exists is not None:
            skipped_count += 1
            continue

        seed = SeedLigand(
            ligand_id=new_id("LIG"),
            project_id=project.project_id,
            target_id=project.target_id,
            name=drug.drug_name,
            smiles=smiles,
            activity_value=None,
            activity_unit=None,
            source=_seed_source(drug),
        )
        db.add(seed)
        db.flush()
        created_ids.append(seed.ligand_id)

    return {
        "created_count": len(created_ids),
        "skipped_count": skipped_count,
        "seed_ligand_ids": created_ids,
    }


def ensure_project_target(
    db: Session,
    target_id: str | None,
    target_name: str | None = None,
) -> Target | None:
    if not target_id:
        return None

    target = db.query(Target).filter_by(target_id=target_id).one_or_none()
    if target is not None:
        return target

    display_name = (target_name or target_id).strip() or target_id
    target = Target(
        target_id=target_id,
        name=display_name,
        aliases=[],
        uniprot_id=None,
        species=None,
        pdb_ids=[],
        pocket_summary=None,
        summary=(
            "User-defined target created from project setup. Upload a receptor/PDB "
            "or add pocket details before structure-based assessment."
        ),
    )
    db.add(target)
    db.flush()
    return target


def _upsert_builtin_binding_site(db: Session, target_id: str, site_payload: dict) -> None:
    binding_site_id = site_payload["binding_site_id"]
    site = db.query(BindingSite).filter_by(binding_site_id=binding_site_id).one_or_none()
    if site is None:
        site = BindingSite(
            binding_site_id=binding_site_id,
            project_id=None,
            target_id=target_id,
        )
        db.add(site)

    grid_box = {
        **(site_payload.get("grid_box") or {}),
        "site_name": site_payload.get("site_name"),
        "reference_ligand": site_payload.get("reference_ligand"),
        "source_url": site_payload.get("source_url"),
    }
    site.project_id = None
    site.target_id = target_id
    site.pdb_id = site_payload.get("pdb_id")
    site.source_file_id = None
    site.receptor_file = site_payload.get("source_url")
    site.prepared_receptor_file = None
    site.preparation_status = "builtin_pocket"
    site.key_residues = site_payload.get("key_residues", [])
    site.grid_box = grid_box
    site.preparation_json = {
        "adapter_mode": "builtin_pdb_ligand_box",
        "labels": ["target_level_binding_site", "builtin_pocket", "pdb_ligand_box"],
        "warnings": ["receptor_file_not_prepared"],
        "tool_status": {},
    }


def _seed_source(drug: TargetDrugLibrary) -> str:
    if drug.pubchem_cid is not None:
        return f"builtin_target_library:pubchem:{drug.pubchem_cid}"
    return "builtin_target_library"
