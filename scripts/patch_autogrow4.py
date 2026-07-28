"""Apply MedAgent's deterministic AutoGrow4 v4.0.3 runtime extensions."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


EXPECTED_AUTOGROW_COMMIT = "1b47b3fe2d9faa76a904533bea2312326a3f44c5"


def _replace_once(
    path: Path,
    old: str,
    new: str,
    marker: str,
    *,
    legacy_marker: str | None = None,
) -> None:
    content = path.read_text(encoding="utf-8")
    if marker in content:
        return
    if legacy_marker and legacy_marker in content:
        return
    if old not in content:
        raise RuntimeError(f"unsupported AutoGrow source layout: {path} lacks {marker!r}")
    path.write_text(content.replace(old, new, 1), encoding="utf-8")


def _upgrade_mutation_fill(path: Path) -> None:
    """Replace an older unbounded mutation-fill block in an installed checkout."""
    content = path.read_text(encoding="utf-8")
    marker = "target_mutant_count = existing_mutant_count + shortfall"
    if marker in content:
        return
    anchor = 'print("Attempting to fill the gap with {} extra mutations.".format(shortfall))'
    anchor_index = content.find(anchor)
    if anchor_index < 0:
        raise RuntimeError(f"unsupported AutoGrow source layout: {path} lacks mutation fill")
    start = content.find("        extra_mutants = []", anchor_index)
    end = content.find("\n        if extra_mutants:", start)
    if start < 0 or end < 0:
        raise RuntimeError(f"unsupported AutoGrow mutation fill layout: {path}")
    replacement = '''        MAX_MUTATION_FILL_ATTEMPTS = 10
        existing_mutant_count = len(new_mutation_smiles_list)
        target_mutant_count = existing_mutant_count + shortfall
        extra_mutants = []
        fill_attempts = 0
        while (
            len(extra_mutants) < shortfall
            and fill_attempts < MAX_MUTATION_FILL_ATTEMPTS
        ):
            fill_attempts += 1
            supplemented_mutants = Mutation.make_mutants(
                vars,
                generation_num,
                number_of_processors,
                target_mutant_count,
                seed_list_mutations,
                list(new_mutation_smiles_list) + extra_mutants,
                rxn_library_variables,
            )
            if supplemented_mutants is None:
                break
            supplemented_mutants = [x for x in supplemented_mutants if x is not None]
            previous_extra_count = len(extra_mutants)
            extra_mutants = supplemented_mutants[
                existing_mutant_count:target_mutant_count
            ]
            if len(extra_mutants) == previous_extra_count:
                break
'''
    path.write_text(content[:start] + replacement + content[end:], encoding="utf-8")


def apply_patch(autogrow_root: Path) -> None:
    root = autogrow_root.resolve()
    entrypoint = root / "RunAutogrow.py"
    if not entrypoint.is_file():
        raise RuntimeError(f"AutoGrow4 entrypoint not found: {entrypoint}")

    execute_docking = root / "autogrow/docking/execute_docking.py"
    _replace_once(
        execute_docking,
        '''    smiles_names_failed_to_dock = vars["parallelizer"].run(
        job_input_dock_lig, run_dock_multithread
    )
''',
        '''    if hasattr(docking_object, "run_batch_dock"):
        # Vina-GPU is generation-wide; per-ligand workers contend for one GPU.
        smiles_names_failed_to_dock = docking_object.run_batch_dock(pdbqts_in_folder)
    else:
        smiles_names_failed_to_dock = vars["parallelizer"].run(
            job_input_dock_lig, run_dock_multithread
        )
''',
        'hasattr(docking_object, "run_batch_dock")',
    )

    operations = root / "autogrow/operators/operations.py"
    _replace_once(
        operations,
        '''    if (
            new_crossover_smiles_list is None
            or len(new_crossover_smiles_list) < num_crossovers
    ):
        print("")
        print("")
        print("We needed to make {} ligands through Crossover".format(num_crossovers))
        print(
            "We only made {} ligands through Crossover".format(
                len(new_crossover_smiles_list)
            )
        )
        print("")
        print("")
        raise Exception("Crossover failed to make enough new ligands.")
''',
        '''    if (
            new_crossover_smiles_list is not None
            and len(new_crossover_smiles_list) < num_crossovers
    ):
        # Fill a crossover shortfall with mutations instead of losing a run.
        shortfall = num_crossovers - len(new_crossover_smiles_list)
        print("")
        print("Crossover only made {} / {} ligands.".format(
            len(new_crossover_smiles_list), num_crossovers))
        print("Attempting to fill the gap with {} extra mutations.".format(shortfall))
        print("")

        MAX_MUTATION_FILL_ATTEMPTS = 10
        existing_mutant_count = len(new_mutation_smiles_list)
        target_mutant_count = existing_mutant_count + shortfall
        extra_mutants = []
        fill_attempts = 0
        while (
            len(extra_mutants) < shortfall
            and fill_attempts < MAX_MUTATION_FILL_ATTEMPTS
        ):
            fill_attempts += 1
            supplemented_mutants = Mutation.make_mutants(
                vars,
                generation_num,
                number_of_processors,
                target_mutant_count,
                seed_list_mutations,
                list(new_mutation_smiles_list) + extra_mutants,
                rxn_library_variables,
            )
            if supplemented_mutants is None:
                break
            supplemented_mutants = [x for x in supplemented_mutants if x is not None]
            previous_extra_count = len(extra_mutants)
            extra_mutants = supplemented_mutants[
                existing_mutant_count:target_mutant_count
            ]
            if len(extra_mutants) == previous_extra_count:
                break

        if extra_mutants:
            print("Filled {} / {} crossover gap with extra mutations.".format(
                len(extra_mutants), shortfall))
            new_mutation_smiles_list.extend(extra_mutants)
            save_ligand_list(
                vars["output_directory"],
                generation_num,
                new_mutation_smiles_list,
                "Chosen_Mutants",
            )
''',
        "target_mutant_count = existing_mutant_count + shortfall",
        legacy_marker="Attempting to fill the gap with {} extra mutations.",
    )

    _upgrade_mutation_fill(operations)

    crossover = root / "autogrow/operators/crossover/execute_crossover.py"
    _replace_once(
        crossover,
        "import autogrow.operators.convert_files.gypsum_dl.gypsum_dl.MolObjectHandling as MOH\n",
        '''import autogrow.operators.convert_files.gypsum_dl.gypsum_dl.MolObjectHandling as MOH

# Stop an unproductive crossover loop so mutations can fill its shortfall.
MAX_CROSSOVER_ATTEMPTS = 200
''',
        "MAX_CROSSOVER_ATTEMPTS = 200",
    )
    _replace_once(
        crossover,
        '''    loop_counter = 0
    while loop_counter < 2000 and len(new_ligands_list) < num_crossovers_to_make:

        react_list = copy.deepcopy(list_previous_gen_smiles)
''',
        '''    loop_counter = 0
    consecutive_failures = 0
    while loop_counter < 2000 and len(new_ligands_list) < num_crossovers_to_make:

        react_list = copy.deepcopy(list_previous_gen_smiles)
        previous_count = len(new_ligands_list)
''',
        "consecutive_failures = 0",
    )
    _replace_once(
        crossover,
        '''        loop_counter = loop_counter + 1

    if len(new_ligands_list) < num_crossovers_to_make:
''',
        '''        loop_counter = loop_counter + 1

        if len(new_ligands_list) == previous_count:
            consecutive_failures += 1
        else:
            consecutive_failures = 0
        if consecutive_failures >= MAX_CROSSOVER_ATTEMPTS:
            break

    if len(new_ligands_list) < num_crossovers_to_make:
''',
        "consecutive_failures >= MAX_CROSSOVER_ATTEMPTS",
    )

    template = Path(__file__).with_name("autogrow4_vendor") / "vina_gpu_batch_docking.py"
    destination = (
        root
        / "autogrow/docking/docking_class/docking_class_children/vina_gpu_batch_docking.py"
    )
    shutil.copy2(template, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(".local/tools/AutoGrow4"),
        help="AutoGrow4 v4.0.3 source root",
    )
    args = parser.parse_args()
    apply_patch(args.root)
    print(f"MedAgent AutoGrow4 extensions ready: {args.root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
