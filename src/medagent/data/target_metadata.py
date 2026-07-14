import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any


TARGET_METADATA: dict[str, dict[str, Any]] = {
    "TGT-EGFR": {
        "pocket_summary": "ATP hinge pocket around the EGFR kinase domain, represented by 4ZAU ligand YY3.",
        "binding_sites": [
            {
                "binding_site_id": "SITE-TGT-EGFR-4ZAU",
                "site_name": "EGFR ATP hinge pocket",
                "pdb_id": "4ZAU",
                "reference_ligand": "YY3 A 1101",
                "source_url": "https://www.rcsb.org/structure/4ZAU",
                "grid_box": {
                    "center": [-0.211, -50.287, 17.977],
                    "size": [16.852, 14.884, 21.496],
                    "unit": "angstrom",
                    "method": "RCSB ligand heavy-atom bounding box with 8 A padding",
                },
                "key_residues": [
                    "ALA743:A",
                    "ASP800:A",
                    "CYS797:A",
                    "GLN791:A",
                    "GLY719:A",
                    "GLY796:A",
                    "LEU718:A",
                    "LEU792:A",
                    "LEU844:A",
                    "LYS728:A",
                    "LYS745:A",
                    "MET793:A",
                    "PHE795:A",
                    "PRO794:A",
                    "THR790:A",
                    "VAL726:A",
                ],
            }
        ],
        "sar_rules": [
            {
                "rule_id": "EGFR-SAR-001",
                "title": "Preserve hinge-binding heteroaromatic core",
                "rationale": "EGFR inhibitors usually need a stable hinge interaction near MET793.",
                "preferred_change": "Tune solvent-exposed substituents before replacing the hinge binder.",
                "avoid": "Removing the hinge HBA pattern without a replacement interaction.",
                "evidence_level": "MVP curated",
            },
            {
                "rule_id": "EGFR-SAR-002",
                "title": "Treat covalent warheads as explicit design constraints",
                "rationale": "CYS797 covalent designs need controlled electrophile geometry and reactivity.",
                "preferred_change": "Keep acrylamide-like warheads only when covalent EGFR is intended.",
                "avoid": "Unscored reactive Michael acceptors in non-covalent rounds.",
                "evidence_level": "MVP curated",
            },
            {
                "rule_id": "EGFR-SAR-003",
                "title": "Reduce hERG pressure from lipophilic anilines",
                "rationale": "Large hydrophobic aniline regions can increase hERG and CYP risk.",
                "preferred_change": "Add moderate polarity on the solvent side while keeping TPSA in range.",
                "avoid": "Stacking extra lipophilic aryl rings without potency evidence.",
                "evidence_level": "MVP curated",
            },
        ],
        "admet_risks": [
            {
                "risk_id": "EGFR-ADMET-001",
                "category": "cardiotoxicity",
                "signal": "hERG risk can rise with high aromaticity and cLogP.",
                "mitigation": "Prefer cLogP 2-4 and avoid extra basic lipophilic motifs.",
                "severity": "medium",
            },
            {
                "risk_id": "EGFR-ADMET-002",
                "category": "reactivity",
                "signal": "Covalent warheads require selectivity review.",
                "mitigation": "Flag electrophile-containing molecules for covalent-specific review.",
                "severity": "high",
            },
        ],
    },
    "TGT-ALK": {
        "pocket_summary": "ALK ATP pocket represented by 2XP2 ligand VGH near the kinase hinge.",
        "binding_sites": [
            {
                "binding_site_id": "SITE-TGT-ALK-2XP2",
                "site_name": "ALK ATP hinge pocket",
                "pdb_id": "2XP2",
                "reference_ligand": "VGH A 9000",
                "source_url": "https://www.rcsb.org/structure/2XP2",
                "grid_box": {
                    "center": [29.923, 47.066, 8.539],
                    "size": [18.049, 18.848, 14.805],
                    "unit": "angstrom",
                    "method": "RCSB ligand heavy-atom bounding box with 8 A padding",
                },
                "key_residues": [
                    "ALA1148:A",
                    "ALA1200:A",
                    "ARG1253:A",
                    "ASN1254:A",
                    "ASP1203:A",
                    "ASP1270:A",
                    "CYS1255:A",
                    "GLU1197:A",
                    "GLY1123:A",
                    "GLY1201:A",
                    "GLY1202:A",
                    "GLY1269:A",
                    "LEU1122:A",
                    "LEU1196:A",
                    "LEU1198:A",
                    "LEU1256:A",
                    "LYS1150:A",
                    "MET1199:A",
                    "VAL1130:A",
                    "VAL1180:A",
                ],
            }
        ],
        "sar_rules": [
            {
                "rule_id": "ALK-SAR-001",
                "title": "Keep a hinge-compatible aza-heteroaromatic donor/acceptor pattern",
                "rationale": "ALK potency is sensitive to the ATP hinge binder geometry.",
                "preferred_change": "Explore solvent-front substituents for selectivity and resistance coverage.",
                "avoid": "Bulky substitutions that clash near the gatekeeper region.",
                "evidence_level": "MVP curated",
            },
            {
                "rule_id": "ALK-SAR-002",
                "title": "Use basic solubilizing groups deliberately",
                "rationale": "ALK inhibitors often use piperidine or piperazine groups for exposure.",
                "preferred_change": "Tune pKa and polar surface area instead of simply increasing basicity.",
                "avoid": "Highly basic lipophilic amines that increase hERG and CYP liability.",
                "evidence_level": "MVP curated",
            },
        ],
        "admet_risks": [
            {
                "risk_id": "ALK-ADMET-001",
                "category": "DDI",
                "signal": "Kinase inhibitor scaffolds can show CYP3A4/CYP2D6 interaction risk.",
                "mitigation": "Track CYP flags together with cLogP and basic amine count.",
                "severity": "medium",
            },
            {
                "risk_id": "ALK-ADMET-002",
                "category": "cardiotoxicity",
                "signal": "Basic lipophilic side chains can elevate hERG risk.",
                "mitigation": "Prefer balanced polarity and avoid excess aromatic ring count.",
                "severity": "medium",
            },
        ],
    },
    "TGT-BRAF": {
        "pocket_summary": "BRAF ATP pocket represented by 3OG7 ligand 032 in the kinase active site.",
        "binding_sites": [
            {
                "binding_site_id": "SITE-TGT-BRAF-3OG7",
                "site_name": "BRAF ATP hinge pocket",
                "pdb_id": "3OG7",
                "reference_ligand": "032 A 1",
                "source_url": "https://www.rcsb.org/structure/3OG7",
                "grid_box": {
                    "center": [1.869, -2.638, -19.918],
                    "size": [24.305, 13.133, 14.396],
                    "unit": "angstrom",
                    "method": "RCSB ligand heavy-atom bounding box with 8 A padding",
                },
                "key_residues": [
                    "ALA481:A",
                    "ASP594:A",
                    "CYS532:A",
                    "GLN530:A",
                    "GLY534:A",
                    "GLY593:A",
                    "GLY596:A",
                    "ILE463:A",
                    "ILE527:A",
                    "LEU505:A",
                    "LEU514:A",
                    "LEU515:A",
                    "LYS483:A",
                    "PHE516:A",
                    "PHE583:A",
                    "PHE595:A",
                    "SER535:A",
                    "SER536:A",
                    "THR529:A",
                    "TRP531:A",
                    "VAL471:A",
                    "VAL482:A",
                ],
            }
        ],
        "sar_rules": [
            {
                "rule_id": "BRAF-SAR-001",
                "title": "Maintain hinge and DFG-pocket complementarity",
                "rationale": "BRAF inhibitors rely on hinge binding plus hydrophobic pocket occupancy.",
                "preferred_change": "Modify solvent-exposed aryl/sulfonamide vectors first.",
                "avoid": "Large polar groups buried in the hydrophobic kinase pocket.",
                "evidence_level": "MVP curated",
            },
            {
                "rule_id": "BRAF-SAR-002",
                "title": "Watch pan-RAF and paradoxical activation hypotheses",
                "rationale": "BRAF design decisions should track isoform selectivity signals.",
                "preferred_change": "Add selectivity notes when changing type-I/type-II binding features.",
                "avoid": "Treating kinase docking score as sufficient selectivity evidence.",
                "evidence_level": "MVP curated",
            },
        ],
        "admet_risks": [
            {
                "risk_id": "BRAF-ADMET-001",
                "category": "solubility",
                "signal": "Hydrophobic kinase scaffolds often carry low solubility risk.",
                "mitigation": "Use solvent-facing polarity and monitor TPSA/logP together.",
                "severity": "medium",
            },
            {
                "risk_id": "BRAF-ADMET-002",
                "category": "DDI",
                "signal": "Aromatic-rich kinase inhibitors can show CYP liability.",
                "mitigation": "Flag CYP3A4 and CYP2D6 predictions in ranking.",
                "severity": "medium",
            },
        ],
    },
    "TGT-KRAS-G12C": {
        "pocket_summary": "KRAS G12C switch-II pocket represented by 6OIM ligand MOV near CYS12.",
        "binding_sites": [
            {
                "binding_site_id": "SITE-TGT-KRAS-G12C-6OIM",
                "site_name": "KRAS G12C switch-II pocket",
                "pdb_id": "6OIM",
                "reference_ligand": "MOV A 303",
                "source_url": "https://www.rcsb.org/structure/6OIM",
                "grid_box": {
                    "center": [1.872, -8.26, -1.361],
                    "size": [21.914, 19.691, 13.876],
                    "unit": "angstrom",
                    "method": "RCSB ligand heavy-atom bounding box with 8 A padding",
                },
                "key_residues": [
                    "ALA11:A",
                    "ALA59:A",
                    "ARG68:A",
                    "ASP69:A",
                    "ASP92:A",
                    "CYS12:A",
                    "GLN61:A",
                    "GLN99:A",
                    "GLU62:A",
                    "GLU63:A",
                    "GLY10:A",
                    "GLY13:A",
                    "GLY60:A",
                    "HIS95:A",
                    "ILE100:A",
                    "LYS16:A",
                    "MET72:A",
                    "PRO34:A",
                    "THR58:A",
                    "TYR96:A",
                    "VAL103:A",
                    "VAL9:A",
                ],
            }
        ],
        "sar_rules": [
            {
                "rule_id": "KRAS-SAR-001",
                "title": "Preserve CYS12-directed covalent geometry",
                "rationale": "KRAS G12C inhibitors depend on warhead orientation toward CYS12.",
                "preferred_change": "Keep warhead distance and vector fixed while exploring pocket substituents.",
                "avoid": "Moving the electrophile without covalent-pose review.",
                "evidence_level": "MVP curated",
            },
            {
                "rule_id": "KRAS-SAR-002",
                "title": "Fill switch-II pocket without excess size",
                "rationale": "The induced switch-II pocket is shallow and sensitive to steric load.",
                "preferred_change": "Use compact hydrophobic groups and preserve polar anchors.",
                "avoid": "High MW aromatic expansion that hurts permeability.",
                "evidence_level": "MVP curated",
            },
        ],
        "admet_risks": [
            {
                "risk_id": "KRAS-ADMET-001",
                "category": "reactivity",
                "signal": "Acrylamide-like covalent warheads require off-target reactivity review.",
                "mitigation": "Carry a covalent-reactivity flag into self-refutation.",
                "severity": "high",
            },
            {
                "risk_id": "KRAS-ADMET-002",
                "category": "permeability",
                "signal": "Large switch-II-pocket molecules can lose permeability.",
                "mitigation": "Track TPSA, rotatable bonds, and MW before ranking.",
                "severity": "medium",
            },
        ],
    },
    "TGT-JAK2": {
        "pocket_summary": "JAK2 kinase ATP pocket represented by 3KRR ligand DQX.",
        "binding_sites": [
            {
                "binding_site_id": "SITE-TGT-JAK2-3KRR",
                "site_name": "JAK2 ATP hinge pocket",
                "pdb_id": "3KRR",
                "reference_ligand": "DQX A 1",
                "source_url": "https://www.rcsb.org/structure/3KRR",
                "grid_box": {
                    "center": [15.13, 11.389, 4.134],
                    "size": [16.34, 23.896, 14.235],
                    "unit": "angstrom",
                    "method": "RCSB ligand heavy-atom bounding box with 8 A padding",
                },
                "key_residues": [
                    "ALA880:A",
                    "ARG980:A",
                    "ASN859:A",
                    "ASN981:A",
                    "ASP994:A",
                    "GLN853:A",
                    "GLU930:A",
                    "GLY856:A",
                    "GLY858:A",
                    "GLY861:A",
                    "GLY935:A",
                    "GLY993:A",
                    "LEU855:A",
                    "LEU932:A",
                    "LEU983:A",
                    "LYS857:A",
                    "LYS882:A",
                    "MET929:A",
                    "PRO933:A",
                    "SER862:A",
                    "SER936:A",
                    "TYR931:A",
                    "TYR934:A",
                    "VAL863:A",
                    "VAL911:A",
                ],
            }
        ],
        "sar_rules": [
            {
                "rule_id": "JAK2-SAR-001",
                "title": "Preserve hinge-binding heteroaromatic motif",
                "rationale": "JAK2 ATP-site potency is hinge-interaction driven.",
                "preferred_change": "Explore selectivity vectors outside the hinge core.",
                "avoid": "Removing hinge acceptors before docking and SAR review.",
                "evidence_level": "MVP curated",
            },
            {
                "rule_id": "JAK2-SAR-002",
                "title": "Track JAK-family selectivity explicitly",
                "rationale": "JAK1/JAK2/JAK3/TYK2 similarity makes selectivity a primary design risk.",
                "preferred_change": "Mark changes expected to affect family selectivity.",
                "avoid": "Ranking only by JAK2 docking score.",
                "evidence_level": "MVP curated",
            },
        ],
        "admet_risks": [
            {
                "risk_id": "JAK2-ADMET-001",
                "category": "selectivity",
                "signal": "JAK-family off-target activity can narrow safety margin.",
                "mitigation": "Treat selectivity evidence as a self-refutation factor.",
                "severity": "medium",
            },
            {
                "risk_id": "JAK2-ADMET-002",
                "category": "DDI",
                "signal": "Basic heteroaromatic kinase inhibitors can trigger CYP flags.",
                "mitigation": "Prioritize low CYP3A4/CYP2D6 predicted risk in ranking.",
                "severity": "medium",
            },
        ],
    },
    "TGT-BTK": {
        "pocket_summary": "BTK ATP pocket represented by 3GEN ligand B43 near the kinase hinge.",
        "binding_sites": [
            {
                "binding_site_id": "SITE-TGT-BTK-3GEN",
                "site_name": "BTK ATP pocket",
                "pdb_id": "3GEN",
                "reference_ligand": "B43 A 1",
                "source_url": "https://www.rcsb.org/structure/3GEN",
                "grid_box": {
                    "center": [-17.36, 6.472, -14.948],
                    "size": [18.056, 12.232, 19.392],
                    "unit": "angstrom",
                    "method": "RCSB ligand heavy-atom bounding box with 8 A padding",
                },
                "key_residues": [
                    "ALA428:A",
                    "ALA478:A",
                    "ASP539:A",
                    "CYS481:A",
                    "GLU475:A",
                    "GLY409:A",
                    "GLY480:A",
                    "ILE472:A",
                    "LEU408:A",
                    "LEU460:A",
                    "LEU528:A",
                    "LEU542:A",
                    "LYS430:A",
                    "MET449:A",
                    "MET477:A",
                    "PHE540:A",
                    "SER538:A",
                    "THR474:A",
                    "TYR476:A",
                    "VAL416:A",
                    "VAL458:A",
                ],
            }
        ],
        "sar_rules": [
            {
                "rule_id": "BTK-SAR-001",
                "title": "Keep covalent CYS481 vector only for covalent BTK rounds",
                "rationale": "Covalent BTK inhibitors rely on correct warhead orientation to CYS481.",
                "preferred_change": "Separate covalent and reversible design hypotheses.",
                "avoid": "Mixing covalent warheads into reversible-only optimization.",
                "evidence_level": "MVP curated",
            },
            {
                "rule_id": "BTK-SAR-002",
                "title": "Balance selectivity against TEC-family kinases",
                "rationale": "BTK pocket similarity can create off-target kinase activity.",
                "preferred_change": "Track hinge and back-pocket modifications as selectivity drivers.",
                "avoid": "Expanding aromatic surface without selectivity evidence.",
                "evidence_level": "MVP curated",
            },
        ],
        "admet_risks": [
            {
                "risk_id": "BTK-ADMET-001",
                "category": "reactivity",
                "signal": "Covalent acrylamide motifs need off-target reactivity review.",
                "mitigation": "Route covalent candidates into high-scrutiny decision cards.",
                "severity": "high",
            },
            {
                "risk_id": "BTK-ADMET-002",
                "category": "DDI",
                "signal": "BTK inhibitor scaffolds can carry CYP3A4 substrate/inhibition risk.",
                "mitigation": "Flag CYP and P-gp outputs in ADMET overview.",
                "severity": "medium",
            },
        ],
    },
    "TGT-CDK4-6": {
        "pocket_summary": "CDK6 ATP pocket represented by 2EUF ligand LQQ on chain B.",
        "binding_sites": [
            {
                "binding_site_id": "SITE-TGT-CDK4-6-2EUF",
                "site_name": "CDK4/6 ATP pocket",
                "pdb_id": "2EUF",
                "reference_ligand": "LQQ B 401",
                "source_url": "https://www.rcsb.org/structure/2EUF",
                "grid_box": {
                    "center": [30.3, 21.972, 60.273],
                    "size": [15.971, 21.861, 15.21],
                    "unit": "angstrom",
                    "method": "RCSB ligand heavy-atom bounding box with 8 A padding",
                },
                "key_residues": [
                    "ALA162:B",
                    "ALA41:B",
                    "ASN150:B",
                    "ASP102:B",
                    "ASP104:B",
                    "ASP163:B",
                    "GLN103:B",
                    "GLN149:B",
                    "GLU21:B",
                    "GLU61:B",
                    "GLU99:B",
                    "GLY20:B",
                    "GLY22:B",
                    "HIS100:B",
                    "ILE19:B",
                    "LEU152:B",
                    "LYS43:B",
                    "PHE164:B",
                    "PHE98:B",
                    "THR107:B",
                    "VAL101:B",
                    "VAL27:B",
                    "VAL77:B",
                ],
            }
        ],
        "sar_rules": [
            {
                "rule_id": "CDK46-SAR-001",
                "title": "Preserve aminopyrimidine-like hinge binding",
                "rationale": "CDK4/6 inhibitors typically rely on hinge-directed heteroaromatics.",
                "preferred_change": "Use solvent-channel amines to tune exposure.",
                "avoid": "Overpacking the ATP pocket with bulky aryl groups.",
                "evidence_level": "MVP curated",
            },
            {
                "rule_id": "CDK46-SAR-002",
                "title": "Track basic amine liability",
                "rationale": "Basic side chains can improve potency and exposure but raise hERG/lysosomal risk.",
                "preferred_change": "Tune amine pKa and reduce aromatic lipophilicity.",
                "avoid": "Adding multiple basic centers without ADMET justification.",
                "evidence_level": "MVP curated",
            },
        ],
        "admet_risks": [
            {
                "risk_id": "CDK46-ADMET-001",
                "category": "cardiotoxicity",
                "signal": "Basic lipophilic CDK4/6 scaffolds can raise hERG alerts.",
                "mitigation": "Apply hERG and cLogP penalties early.",
                "severity": "medium",
            },
            {
                "risk_id": "CDK46-ADMET-002",
                "category": "distribution",
                "signal": "High basicity may increase tissue trapping.",
                "mitigation": "Monitor pKa proxies, TPSA, and P-gp risk.",
                "severity": "medium",
            },
        ],
    },
    "TGT-PARP1": {
        "pocket_summary": "PARP1 catalytic pocket represented by 4UND ligand 2YQ.",
        "binding_sites": [
            {
                "binding_site_id": "SITE-TGT-PARP1-4UND",
                "site_name": "PARP1 catalytic nicotinamide pocket",
                "pdb_id": "4UND",
                "reference_ligand": "2YQ A 2011",
                "source_url": "https://www.rcsb.org/structure/4UND",
                "grid_box": {
                    "center": [1.146, 63.743, 188.035],
                    "size": [18.222, 16.378, 13.762],
                    "unit": "angstrom",
                    "method": "RCSB ligand heavy-atom bounding box with 8 A padding",
                },
                "key_residues": [
                    "ALA898:A",
                    "ARG878:A",
                    "ASN987:A",
                    "ASP766:A",
                    "GLN759:A",
                    "GLU763:A",
                    "GLU988:A",
                    "GLY863:A",
                    "GLY888:A",
                    "GLY894:A",
                    "HIS862:A",
                    "ILE895:A",
                    "LYS903:A",
                    "PHE897:A",
                    "SER864:A",
                    "SER904:A",
                    "THR887:A",
                    "TRP861:A",
                    "TYR889:A",
                    "TYR896:A",
                    "TYR907:A",
                ],
            }
        ],
        "sar_rules": [
            {
                "rule_id": "PARP1-SAR-001",
                "title": "Preserve nicotinamide-mimic H-bonding",
                "rationale": "PARP inhibitors usually mimic NAD+ nicotinamide interactions in the catalytic site.",
                "preferred_change": "Modify outer solvent-facing vectors before changing the amide mimic.",
                "avoid": "Removing the key carbonyl/heteroatom pattern without replacement.",
                "evidence_level": "MVP curated",
            },
            {
                "rule_id": "PARP1-SAR-002",
                "title": "Control planarity and polarity",
                "rationale": "PARP scaffolds need aromatic stacking but can become too flat or lipophilic.",
                "preferred_change": "Add modest polarity while preserving catalytic pocket fit.",
                "avoid": "Excessive fused aromatic expansion.",
                "evidence_level": "MVP curated",
            },
        ],
        "admet_risks": [
            {
                "risk_id": "PARP1-ADMET-001",
                "category": "permeability",
                "signal": "High polarity can reduce cell permeability.",
                "mitigation": "Balance TPSA and HBD count against potency.",
                "severity": "medium",
            },
            {
                "risk_id": "PARP1-ADMET-002",
                "category": "DDI",
                "signal": "Flat aromatic systems can trigger CYP and clearance risk.",
                "mitigation": "Track CYP flags and aromatic ring count.",
                "severity": "medium",
            },
        ],
    },
    "TGT-PI3K": {
        "pocket_summary": "PI3K alpha ATP pocket represented by 4JPS ligand 1LT.",
        "binding_sites": [
            {
                "binding_site_id": "SITE-TGT-PI3K-4JPS",
                "site_name": "PI3K ATP pocket",
                "pdb_id": "4JPS",
                "reference_ligand": "1LT A 1102",
                "source_url": "https://www.rcsb.org/structure/4JPS",
                "grid_box": {
                    "center": [-1.319, -9.513, 16.948],
                    "size": [14.946, 15.659, 21.114],
                    "unit": "angstrom",
                    "method": "RCSB ligand heavy-atom bounding box with 8 A padding",
                },
                "key_residues": [
                    "ARG770:A",
                    "ARG852:A",
                    "ASN853:A",
                    "ASP933:A",
                    "GLN859:A",
                    "GLU849:A",
                    "HIS855:A",
                    "ILE800:A",
                    "ILE848:A",
                    "ILE932:A",
                    "LYS802:A",
                    "MET772:A",
                    "MET922:A",
                    "PHE930:A",
                    "PRO778:A",
                    "SER774:A",
                    "SER854:A",
                    "THR856:A",
                    "TRP780:A",
                    "TYR836:A",
                    "VAL850:A",
                    "VAL851:A",
                ],
            }
        ],
        "sar_rules": [
            {
                "rule_id": "PI3K-SAR-001",
                "title": "Preserve hinge interaction while tuning isoform pocket contacts",
                "rationale": "PI3K isoform selectivity depends on subtle pocket vectors.",
                "preferred_change": "Annotate alpha/delta/gamma selectivity hypothesis for each core change.",
                "avoid": "Treating pan-PI3K docking as sufficient for a selective program.",
                "evidence_level": "MVP curated",
            },
            {
                "rule_id": "PI3K-SAR-002",
                "title": "Avoid excessive lipophilic pocket filling",
                "rationale": "PI3K inhibitors can become hydrophobic and poorly soluble.",
                "preferred_change": "Use constrained polarity on solvent-exposed substituents.",
                "avoid": "Large hydrophobic appendages without solubility review.",
                "evidence_level": "MVP curated",
            },
        ],
        "admet_risks": [
            {
                "risk_id": "PI3K-ADMET-001",
                "category": "solubility",
                "signal": "Hydrophobic kinase scaffolds can show low aqueous solubility.",
                "mitigation": "Penalize low solubility and high logP in ranking.",
                "severity": "medium",
            },
            {
                "risk_id": "PI3K-ADMET-002",
                "category": "DDI",
                "signal": "CYP3A4 and P-gp liabilities are common watch items.",
                "mitigation": "Expose CYP/P-gp fields in ADMET report cards.",
                "severity": "medium",
            },
        ],
    },
    "TGT-HDAC": {
        "pocket_summary": "HDAC catalytic zinc pocket represented by 1T64 ligand TSN.",
        "binding_sites": [
            {
                "binding_site_id": "SITE-TGT-HDAC-1T64",
                "site_name": "HDAC zinc catalytic pocket",
                "pdb_id": "1T64",
                "reference_ligand": "TSN A 386",
                "source_url": "https://www.rcsb.org/structure/1T64",
                "grid_box": {
                    "center": [61.332, 73.648, 11.759],
                    "size": [13.686, 13.889, 21.375],
                    "unit": "angstrom",
                    "method": "RCSB ligand heavy-atom bounding box with 8 A padding",
                },
                "key_residues": [
                    "ASP101:A",
                    "ASP178:A",
                    "ASP267:A",
                    "GLY151:A",
                    "GLY304:A",
                    "HIS142:A",
                    "HIS143:A",
                    "HIS180:A",
                    "MET274:A",
                    "PHE152:A",
                    "PHE208:A",
                    "TYR100:A",
                    "TYR306:A",
                ],
            }
        ],
        "sar_rules": [
            {
                "rule_id": "HDAC-SAR-001",
                "title": "Maintain zinc-binding group, linker, and cap organization",
                "rationale": "HDAC inhibitors typically require a zinc-binding group, linker, and surface cap.",
                "preferred_change": "Optimize linker length and cap polarity separately.",
                "avoid": "Changing zinc-binding groups without metal-chelation review.",
                "evidence_level": "MVP curated",
            },
            {
                "rule_id": "HDAC-SAR-002",
                "title": "Separate pan-HDAC and isoform-selective hypotheses",
                "rationale": "Broad HDAC inhibition can increase toxicity risk.",
                "preferred_change": "Flag isoform-selectivity intent when changing cap groups.",
                "avoid": "Ranking by zinc-pocket docking alone.",
                "evidence_level": "MVP curated",
            },
        ],
        "admet_risks": [
            {
                "risk_id": "HDAC-ADMET-001",
                "category": "toxicity",
                "signal": "Metal-binding pharmacophores can create broad target engagement.",
                "mitigation": "Use self-refutation to flag broad chelation and pan-HDAC risk.",
                "severity": "high",
            },
            {
                "risk_id": "HDAC-ADMET-002",
                "category": "solubility",
                "signal": "Hydrophobic caps and linkers can reduce solubility.",
                "mitigation": "Tune cap polarity while retaining zinc-pocket reach.",
                "severity": "medium",
            },
        ],
    },
}


def get_target_metadata(target_id: str | None) -> dict[str, Any]:
    if not target_id:
        return {}
    return deepcopy(TARGET_METADATA.get(target_id) or _json_target_metadata().get(target_id, {}))


def get_target_binding_sites(target_id: str | None) -> list[dict[str, Any]]:
    return get_target_metadata(target_id).get("binding_sites", [])


def get_target_sar_rules(target_id: str | None) -> list[dict[str, Any]]:
    return get_target_metadata(target_id).get("sar_rules", [])


def get_target_admet_risks(target_id: str | None) -> list[dict[str, Any]]:
    return get_target_metadata(target_id).get("admet_risks", [])


@lru_cache(maxsize=1)
def _json_target_metadata() -> dict[str, dict[str, Any]]:
    seed_path = Path(__file__).with_name("target_drug_library.json")
    if not seed_path.exists():
        return {}
    try:
        targets = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    metadata_by_id: dict[str, dict[str, Any]] = {}
    for target in targets:
        if not isinstance(target, dict):
            continue
        target_id = target.get("target_id")
        if not target_id:
            continue
        metadata_by_id[target_id] = {
            "pocket_summary": target.get("pocket_summary"),
            "binding_sites": target.get("binding_sites", []),
            "sar_rules": target.get("sar_rules", []),
            "admet_risks": target.get("admet_risks", []),
        }
    return metadata_by_id
