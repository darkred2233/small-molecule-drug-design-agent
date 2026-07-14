from __future__ import annotations

import argparse
import json
import math
import shlex
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_LIBRARY = REPO_ROOT / "src" / "medagent" / "data" / "target_drug_library.json"
CACHE_DIR = REPO_ROOT / ".local" / "data_expansion"
PUBCHEM_CACHE = CACHE_DIR / "pubchem_properties.json"
PDB_CACHE_DIR = CACHE_DIR / "pdb"


@dataclass(frozen=True)
class DrugSpec:
    name: str
    status: str
    mechanism: str
    indication: str


@dataclass(frozen=True)
class PdbLigandSpec:
    pdb_id: str
    ligand: str
    site_name: str


@dataclass(frozen=True)
class TargetSpec:
    target_id: str
    name: str
    aliases: tuple[str, ...]
    uniprot_id: str
    area: str
    family: str
    design_focus: str
    safety_focus: str
    drugs: tuple[DrugSpec, ...]
    pdb_ligand: PdbLigandSpec | None = None
    extra_pdb_ids: tuple[str, ...] = ()


TARGET_SPECS: tuple[TargetSpec, ...] = (
    TargetSpec(
        "TGT-HER2",
        "HER2",
        ("ERBB2", "HER2/neu"),
        "P04626",
        "oncology",
        "kinase",
        "HER2-selective ATP-site inhibition and ERBB2-altered tumor coverage",
        "EGFR-family selectivity, diarrhea/rash liability, and CYP3A4 interaction pressure",
        (
            DrugSpec("lapatinib", "approved", "Dual EGFR/HER2 reversible tyrosine kinase inhibitor", "HER2-positive breast cancer"),
            DrugSpec("neratinib", "approved", "Irreversible pan-HER tyrosine kinase inhibitor", "HER2-positive breast cancer"),
            DrugSpec("tucatinib", "approved", "Selective HER2 tyrosine kinase inhibitor", "HER2-positive breast and colorectal cancer"),
        ),
        PdbLigandSpec("3PP0", "03Q", "HER2 ATP hinge pocket"),
    ),
    TargetSpec(
        "TGT-MET",
        "MET",
        ("c-Met", "HGFR"),
        "P08581",
        "oncology",
        "kinase",
        "MET activation-loop and solvent-front resistant kinase inhibition",
        "CYP3A4 DDI risk, edema signals, and kinase off-target selectivity",
        (
            DrugSpec("capmatinib", "approved", "Selective MET tyrosine kinase inhibitor", "MET exon 14 skipping non-small cell lung cancer"),
            DrugSpec("tepotinib", "approved", "Selective MET tyrosine kinase inhibitor", "MET exon 14 skipping non-small cell lung cancer"),
            DrugSpec("savolitinib", "approved", "Selective MET tyrosine kinase inhibitor", "MET-driven cancers"),
        ),
        PdbLigandSpec("11HQ", "A1C9B", "MET ATP hinge pocket"),
    ),
    TargetSpec(
        "TGT-ROS1",
        "ROS1",
        ("ROS", "c-ros oncogene 1"),
        "P08922",
        "oncology",
        "kinase",
        "ROS1 fusion kinase inhibition with resistance mutation coverage",
        "CNS exposure, QT/hERG, and kinase cross-reactivity",
        (
            DrugSpec("crizotinib", "approved", "ALK/ROS1/MET tyrosine kinase inhibitor", "ROS1-positive non-small cell lung cancer"),
            DrugSpec("entrectinib", "approved", "TRK/ROS1/ALK tyrosine kinase inhibitor", "ROS1-positive NSCLC and NTRK fusion cancers"),
            DrugSpec("repotrectinib", "approved", "ROS1/TRK inhibitor designed for solvent-front resistance", "ROS1-positive NSCLC and NTRK fusion cancers"),
        ),
        PdbLigandSpec("3ZBF", "VGH", "ROS1 ATP hinge pocket"),
    ),
    TargetSpec(
        "TGT-RET",
        "RET",
        ("RET proto-oncogene",),
        "P07949",
        "oncology",
        "kinase",
        "RET gatekeeper and solvent-front resistant kinase inhibition",
        "VEGFR off-target avoidance, hypertension risk, and CYP3A4 metabolism",
        (
            DrugSpec("selpercatinib", "approved", "Selective RET tyrosine kinase inhibitor", "RET fusion-positive NSCLC and RET-mutant thyroid cancer"),
            DrugSpec("pralsetinib", "approved", "Selective RET tyrosine kinase inhibitor", "RET-altered cancers"),
            DrugSpec("vandetanib", "approved", "RET/VEGFR/EGFR tyrosine kinase inhibitor", "Medullary thyroid cancer"),
        ),
        PdbLigandSpec("2IVU", "ZD6", "RET ATP hinge pocket"),
    ),
    TargetSpec(
        "TGT-NTRK",
        "NTRK",
        ("TRKA", "NTRK1", "NTRK2", "NTRK3"),
        "P04629",
        "oncology",
        "kinase",
        "TRK fusion kinase inhibition across first-generation and resistance settings",
        "CNS adverse effects, weight gain, and kinase selectivity",
        (
            DrugSpec("larotrectinib", "approved", "Selective TRK inhibitor", "NTRK fusion-positive solid tumors"),
            DrugSpec("entrectinib", "approved", "TRK/ROS1/ALK tyrosine kinase inhibitor", "NTRK fusion-positive solid tumors"),
            DrugSpec("repotrectinib", "approved", "TRK/ROS1 inhibitor with resistance mutation coverage", "NTRK fusion-positive solid tumors"),
        ),
        PdbLigandSpec("4AOJ", "V4Z", "TRKA ATP hinge pocket"),
    ),
    TargetSpec(
        "TGT-FGFR",
        "FGFR",
        ("FGFR1", "FGFR2", "FGFR3"),
        "P11362",
        "oncology",
        "kinase",
        "FGFR ATP-site inhibition with isoform and gatekeeper mutation awareness",
        "Hyperphosphatemia, ocular toxicity, and pan-FGFR selectivity",
        (
            DrugSpec("erdafitinib", "approved", "Pan-FGFR tyrosine kinase inhibitor", "FGFR-altered urothelial cancer"),
            DrugSpec("pemigatinib", "approved", "FGFR1/2/3 tyrosine kinase inhibitor", "FGFR2 fusion cholangiocarcinoma"),
            DrugSpec("futibatinib", "approved", "Covalent irreversible FGFR inhibitor", "FGFR2 fusion cholangiocarcinoma"),
        ),
        PdbLigandSpec("1AGW", "SU2", "FGFR1 ATP hinge pocket"),
    ),
    TargetSpec(
        "TGT-MEK",
        "MEK1/2",
        ("MAP2K1", "MAP2K2", "MEK"),
        "Q02750",
        "oncology",
        "kinase_allosteric",
        "Allosteric MEK inhibition adjacent to the ATP pocket",
        "Rash, ocular/cardiac monitoring, and MAPK pathway feedback",
        (
            DrugSpec("trametinib", "approved", "Allosteric MEK1/2 inhibitor", "BRAF V600-mutant melanoma and other MAPK-driven tumors"),
            DrugSpec("cobimetinib", "approved", "Allosteric MEK1/2 inhibitor", "BRAF V600-mutant melanoma"),
            DrugSpec("binimetinib", "approved", "Allosteric MEK1/2 inhibitor", "BRAF V600-mutant melanoma"),
        ),
        PdbLigandSpec("1S9J", "BBM", "MEK allosteric inhibitor pocket"),
    ),
    TargetSpec(
        "TGT-MTOR",
        "mTOR",
        ("MTOR", "FRAP1"),
        "P42345",
        "oncology",
        "kinase_allosteric",
        "FRB allosteric modulation and ATP-site mTOR kinase inhibition context",
        "Immunosuppression, metabolic effects, and CYP3A4/P-gp interactions",
        (
            DrugSpec("everolimus", "approved", "mTORC1 inhibitor that binds FKBP12 and the FRB domain", "Cancer, transplant rejection, and tuberous sclerosis complex"),
            DrugSpec("temsirolimus", "approved", "Rapamycin analog mTORC1 inhibitor", "Renal cell carcinoma"),
            DrugSpec("sirolimus", "approved", "mTORC1 inhibitor that binds FKBP12 and the FRB domain", "Transplant rejection and lymphangioleiomyomatosis"),
        ),
        PdbLigandSpec("1FAP", "RAP", "mTOR-FKBP12 rapamycin allosteric interface"),
    ),
    TargetSpec(
        "TGT-AKT1",
        "AKT1",
        ("PKB alpha", "RAC-alpha serine/threonine-protein kinase"),
        "P31749",
        "oncology",
        "kinase",
        "ATP-site and allosteric AKT pathway inhibition",
        "Hyperglycemia, rash, diarrhea, and kinase pathway selectivity",
        (
            DrugSpec("capivasertib", "approved", "Pan-AKT kinase inhibitor", "HR-positive HER2-negative breast cancer with PI3K/AKT pathway alteration"),
            DrugSpec("ipatasertib", "clinical", "ATP-competitive AKT inhibitor", "PI3K/AKT pathway-altered cancers"),
            DrugSpec("afuresertib", "clinical", "ATP-competitive AKT inhibitor", "Hematologic and solid tumors"),
        ),
        PdbLigandSpec("29MJ", "6S1", "AKT1 allosteric inhibitor pocket"),
    ),
    TargetSpec(
        "TGT-CDK2",
        "CDK2",
        ("Cyclin-dependent kinase 2",),
        "P24941",
        "oncology",
        "kinase",
        "ATP-site CDK2 inhibition with CDK-family selectivity",
        "Myelosuppression, cell-cycle selectivity, and broad kinase inhibition",
        (
            DrugSpec("dinaciclib", "clinical", "CDK1/2/5/9 inhibitor", "Cancer clinical studies"),
            DrugSpec("milciclib", "clinical", "Multi-CDK inhibitor", "Cancer clinical studies"),
            DrugSpec("seliciclib", "clinical", "CDK2/7/9 inhibitor", "Cancer and inflammatory disease studies"),
        ),
        PdbLigandSpec("1AQ1", "STU", "CDK2 ATP hinge pocket"),
    ),
    TargetSpec(
        "TGT-CDK9",
        "CDK9",
        ("Cyclin-dependent kinase 9", "P-TEFb"),
        "P50750",
        "oncology",
        "kinase",
        "Transcriptional CDK inhibition with CDK9 potency and selectivity",
        "Transcriptional toxicity, myelosuppression, and cardiac monitoring",
        (
            DrugSpec("alvocidib", "clinical", "CDK9 and pan-CDK inhibitor", "Hematologic malignancy studies"),
            DrugSpec("atuveciclib", "clinical", "CDK9 inhibitor", "Cancer clinical studies"),
            DrugSpec("dinaciclib", "clinical", "CDK1/2/5/9 inhibitor", "Cancer clinical studies"),
        ),
        PdbLigandSpec("3BLR", "CPB", "CDK9 ATP hinge pocket"),
    ),
    TargetSpec(
        "TGT-PARP2",
        "PARP2",
        ("ADP-ribosyltransferase diphtheria toxin-like 2",),
        "Q9UGN5",
        "oncology",
        "enzyme",
        "NAD+-competitive PARP catalytic inhibition and PARP1/PARP2 trapping context",
        "Myelosuppression, anemia, and PARP isoform trapping balance",
        (
            DrugSpec("olaparib", "approved", "PARP1/2 inhibitor", "BRCA-mutated ovarian, breast, pancreatic, and prostate cancers"),
            DrugSpec("talazoparib", "approved", "PARP1/2 inhibitor with strong PARP trapping", "BRCA-mutated breast cancer and prostate cancer"),
            DrugSpec("veliparib", "clinical", "PARP1/2 inhibitor", "DNA damage response clinical studies"),
        ),
        PdbLigandSpec("4PJV", "2YQ", "PARP2 catalytic nicotinamide pocket"),
    ),
    TargetSpec(
        "TGT-BCL2",
        "BCL-2",
        ("BCL2", "B-cell lymphoma 2"),
        "P10415",
        "oncology",
        "protein_protein",
        "BH3 groove occupancy and apoptotic priming",
        "Tumor lysis risk, thrombocytopenia from BCL-XL off-target activity, and high lipophilicity",
        (
            DrugSpec("venetoclax", "approved", "Selective BCL-2 inhibitor", "Chronic lymphocytic leukemia and acute myeloid leukemia"),
            DrugSpec("navitoclax", "clinical", "BCL-2/BCL-XL inhibitor", "Hematologic and solid tumor studies"),
            DrugSpec("obatoclax", "clinical", "Pan-BCL-2 family inhibitor", "Cancer clinical studies"),
        ),
        PdbLigandSpec("1YSW", "43B", "BCL-2 BH3-binding groove"),
    ),
    TargetSpec(
        "TGT-MDM2",
        "MDM2",
        ("HDM2",),
        "Q00987",
        "oncology",
        "protein_protein",
        "p53-binding cleft antagonism and p53 pathway reactivation",
        "Hematologic toxicity, GI tolerability, and high aromaticity",
        (
            DrugSpec("idasanutlin", "clinical", "MDM2-p53 interaction antagonist", "Cancer clinical studies"),
            DrugSpec("navtemadlin", "clinical", "MDM2-p53 interaction antagonist", "Myelofibrosis and solid tumor studies"),
            DrugSpec("milademetan", "clinical", "MDM2-p53 interaction antagonist", "Cancer clinical studies"),
        ),
        PdbLigandSpec("1RV1", "IMZ", "MDM2 p53-binding pocket"),
    ),
    TargetSpec(
        "TGT-DPP4",
        "DPP-4",
        ("DPP4", "CD26"),
        "P27487",
        "metabolic",
        "enzyme",
        "S1/S2 pocket dipeptidyl peptidase inhibition",
        "Renal dose considerations, pancreatitis signals, and selectivity over DPP8/9",
        (
            DrugSpec("sitagliptin", "approved", "DPP-4 inhibitor", "Type 2 diabetes"),
            DrugSpec("saxagliptin", "approved", "DPP-4 inhibitor", "Type 2 diabetes"),
            DrugSpec("linagliptin", "approved", "DPP-4 inhibitor", "Type 2 diabetes"),
        ),
        PdbLigandSpec("1RWQ", "5AP", "DPP-4 catalytic pocket"),
    ),
    TargetSpec(
        "TGT-SGLT2",
        "SGLT2",
        ("SLC5A2", "sodium/glucose cotransporter 2"),
        "P31639",
        "metabolic",
        "transporter",
        "Glucose-binding transporter inhibition with C-glycoside stability",
        "Genitourinary infection risk, ketoacidosis warnings, and renal function context",
        (
            DrugSpec("dapagliflozin", "approved", "SGLT2 inhibitor", "Type 2 diabetes, heart failure, and chronic kidney disease"),
            DrugSpec("empagliflozin", "approved", "SGLT2 inhibitor", "Type 2 diabetes, heart failure, and chronic kidney disease"),
            DrugSpec("canagliflozin", "approved", "SGLT2 inhibitor", "Type 2 diabetes and diabetic kidney disease"),
        ),
        PdbLigandSpec("7VSI", "7R3", "SGLT2 glucose-transporter inhibitor pocket"),
    ),
    TargetSpec(
        "TGT-GLP1R",
        "GLP-1R",
        ("GLP1R", "glucagon-like peptide-1 receptor"),
        "P43220",
        "metabolic",
        "gpcr",
        "Class B GPCR agonism and biased signaling",
        "GI tolerability, peptide exposure, and pancreatitis/gallbladder monitoring context",
        (
            DrugSpec("orforglipron", "clinical", "Oral non-peptide GLP-1 receptor agonist", "Type 2 diabetes and obesity studies"),
            DrugSpec("danuglipron", "clinical", "Oral non-peptide GLP-1 receptor agonist", "Type 2 diabetes and obesity studies"),
            DrugSpec("semaglutide", "approved", "GLP-1 receptor agonist peptide", "Type 2 diabetes and obesity"),
        ),
        PdbLigandSpec("5VEW", "97Y", "GLP-1R transmembrane agonist pocket"),
    ),
    TargetSpec(
        "TGT-PPARG",
        "PPAR-gamma",
        ("PPARG", "NR1C3"),
        "P37231",
        "metabolic",
        "nuclear_receptor",
        "Ligand-binding domain agonism and partial agonism",
        "Fluid retention, weight gain, bone risk, and full agonist liability",
        (
            DrugSpec("pioglitazone", "approved", "PPAR-gamma agonist", "Type 2 diabetes"),
            DrugSpec("rosiglitazone", "approved", "PPAR-gamma agonist", "Type 2 diabetes"),
            DrugSpec("lobeglitazone", "approved", "PPAR-gamma agonist", "Type 2 diabetes"),
        ),
        PdbLigandSpec("1FM6", "BRL", "PPAR-gamma ligand-binding pocket"),
    ),
    TargetSpec(
        "TGT-FFAR1",
        "FFAR1",
        ("GPR40", "free fatty acid receptor 1"),
        "O14842",
        "metabolic",
        "gpcr",
        "Allosteric GPCR agonism for glucose-stimulated insulin secretion",
        "Hepatotoxicity monitoring and high lipophilicity",
        (
            DrugSpec("fasiglifam", "clinical", "FFAR1/GPR40 agonist", "Type 2 diabetes studies"),
            DrugSpec("AMG 837", "clinical", "FFAR1/GPR40 agonist", "Type 2 diabetes studies"),
            DrugSpec("TAK-875", "clinical", "FFAR1/GPR40 agonist", "Type 2 diabetes studies"),
        ),
        PdbLigandSpec("4PHU", "2YB", "FFAR1 allosteric ligand pocket"),
    ),
    TargetSpec(
        "TGT-GCK",
        "Glucokinase",
        ("GCK", "hexokinase IV"),
        "P35557",
        "metabolic",
        "enzyme_allosteric",
        "Allosteric activation of hepatic and pancreatic glucokinase",
        "Hypoglycemia and triglyceride/liver exposure concerns",
        (
            DrugSpec("dorzagliatin", "approved", "Glucokinase activator", "Type 2 diabetes"),
            DrugSpec("piragliatin", "clinical", "Glucokinase activator", "Type 2 diabetes studies"),
            DrugSpec("AZD1656", "clinical", "Glucokinase activator", "Type 2 diabetes studies"),
        ),
        PdbLigandSpec("1V4S", "MRK", "Glucokinase allosteric activator pocket"),
    ),
    TargetSpec(
        "TGT-FXR",
        "FXR",
        ("NR1H4", "bile acid receptor"),
        "Q96RI1",
        "metabolic",
        "nuclear_receptor",
        "Nuclear receptor agonism tuned for bile acid and metabolic signaling",
        "Pruritus, lipid changes, liver safety, and bile-acid pathway effects",
        (
            DrugSpec("obeticholic acid", "approved", "FXR agonist", "Primary biliary cholangitis"),
            DrugSpec("cilofexor", "clinical", "Nonsteroidal FXR agonist", "NASH and cholestatic disease studies"),
            DrugSpec("tropifexor", "clinical", "Nonsteroidal FXR agonist", "NASH and cholestatic disease studies"),
        ),
        PdbLigandSpec("1OSH", "FEX", "FXR ligand-binding pocket"),
    ),
    TargetSpec(
        "TGT-ACC",
        "ACC1/2",
        ("ACACA", "ACACB", "acetyl-CoA carboxylase"),
        "Q13085",
        "metabolic",
        "enzyme",
        "Acetyl-CoA carboxylase inhibition across ACC1/ACC2 isoforms",
        "Hypertriglyceridemia, liver fat handling, and mitochondrial beta-oxidation balance",
        (
            DrugSpec("firsocostat", "clinical", "ACC1/2 inhibitor", "NASH clinical studies"),
            DrugSpec("soraphen A", "tool", "ACC inhibitor natural product", "ACC chemical biology"),
            DrugSpec("ND-630", "clinical", "ACC inhibitor", "NASH and metabolic disease studies"),
        ),
        None,
    ),
    TargetSpec(
        "TGT-ACE",
        "ACE",
        ("angiotensin-converting enzyme", "CD143"),
        "P12821",
        "cardiovascular",
        "metalloprotease",
        "Zinc metalloprotease inhibition with carboxylate/phosphinate/captopril-like anchors",
        "Cough, angioedema, hyperkalemia, renal function, and zinc-binding selectivity",
        (
            DrugSpec("captopril", "approved", "ACE inhibitor", "Hypertension and heart failure"),
            DrugSpec("enalapril", "approved", "ACE inhibitor prodrug", "Hypertension and heart failure"),
            DrugSpec("lisinopril", "approved", "ACE inhibitor", "Hypertension and heart failure"),
        ),
        PdbLigandSpec("1O86", "LPR", "ACE zinc catalytic pocket"),
    ),
    TargetSpec(
        "TGT-AT1R",
        "AT1R",
        ("AGTR1", "angiotensin II receptor type 1"),
        "P30556",
        "cardiovascular",
        "gpcr",
        "Angiotensin II type 1 receptor antagonism",
        "Hyperkalemia, renal function, pregnancy contraindication, and CYP interactions",
        (
            DrugSpec("losartan", "approved", "AT1 receptor antagonist", "Hypertension and diabetic nephropathy"),
            DrugSpec("valsartan", "approved", "AT1 receptor antagonist", "Hypertension and heart failure"),
            DrugSpec("olmesartan", "approved", "AT1 receptor antagonist", "Hypertension"),
        ),
        PdbLigandSpec("4YAY", "ZD7", "AT1R orthosteric antagonist pocket"),
    ),
    TargetSpec(
        "TGT-REN",
        "Renin",
        ("REN", "angiotensinogenase"),
        "P00797",
        "cardiovascular",
        "protease",
        "Aspartyl protease active-site inhibition",
        "Renal function, hyperkalemia, and high polarity/permeability balance",
        (
            DrugSpec("aliskiren", "approved", "Direct renin inhibitor", "Hypertension"),
            DrugSpec("remikiren", "clinical", "Direct renin inhibitor", "Hypertension studies"),
            DrugSpec("enalkiren", "clinical", "Direct renin inhibitor", "Hypertension studies"),
        ),
        PdbLigandSpec("1BIL", "0IU", "Renin aspartyl protease active site"),
    ),
    TargetSpec(
        "TGT-F10",
        "Factor Xa",
        ("F10", "coagulation factor X"),
        "P00742",
        "cardiovascular",
        "protease",
        "S1/S4 pocket serine protease inhibition",
        "Bleeding risk, CYP3A4/P-gp interactions, and renal clearance",
        (
            DrugSpec("apixaban", "approved", "Direct Factor Xa inhibitor", "Stroke prevention and venous thromboembolism"),
            DrugSpec("rivaroxaban", "approved", "Direct Factor Xa inhibitor", "Stroke prevention and venous thromboembolism"),
            DrugSpec("edoxaban", "approved", "Direct Factor Xa inhibitor", "Stroke prevention and venous thromboembolism"),
        ),
        PdbLigandSpec("1EZQ", "RPR", "Factor Xa active site"),
    ),
    TargetSpec(
        "TGT-F2",
        "Thrombin",
        ("F2", "prothrombin"),
        "P00734",
        "cardiovascular",
        "protease",
        "Serine protease active-site and exosite-aware inhibition",
        "Bleeding risk, renal clearance, and peptide-like polarity",
        (
            DrugSpec("dabigatran", "approved", "Direct thrombin inhibitor", "Stroke prevention and venous thromboembolism"),
            DrugSpec("argatroban", "approved", "Direct thrombin inhibitor", "Heparin-induced thrombocytopenia"),
            DrugSpec("bivalirudin", "approved", "Direct thrombin inhibitor peptide", "Anticoagulation during PCI"),
        ),
        PdbLigandSpec("1A3B", "T29", "Thrombin active site"),
    ),
    TargetSpec(
        "TGT-P2Y12",
        "P2Y12",
        ("P2RY12", "ADP receptor P2Y12"),
        "Q9H244",
        "cardiovascular",
        "gpcr",
        "Platelet P2Y12 receptor antagonism",
        "Bleeding risk, CYP2C19 activation for thienopyridines, and dyspnea signal",
        (
            DrugSpec("clopidogrel", "approved", "Irreversible P2Y12 antagonist prodrug", "Acute coronary syndrome and stroke prevention"),
            DrugSpec("ticagrelor", "approved", "Reversible P2Y12 antagonist", "Acute coronary syndrome and stroke prevention"),
            DrugSpec("prasugrel", "approved", "Irreversible P2Y12 antagonist prodrug", "Acute coronary syndrome"),
        ),
        PdbLigandSpec("4NTJ", "AZJ", "P2Y12 antagonist pocket"),
    ),
    TargetSpec(
        "TGT-ADRB1",
        "ADRB1",
        ("beta1-adrenergic receptor", "ADRB1"),
        "P08588",
        "cardiovascular",
        "gpcr",
        "Beta1 adrenergic receptor antagonism with beta2 selectivity context",
        "Bradycardia, bronchospasm selectivity, and CNS penetration",
        (
            DrugSpec("metoprolol", "approved", "Beta1 adrenergic receptor antagonist", "Hypertension, angina, and heart failure"),
            DrugSpec("bisoprolol", "approved", "Beta1 adrenergic receptor antagonist", "Hypertension and heart failure"),
            DrugSpec("atenolol", "approved", "Beta1 adrenergic receptor antagonist", "Hypertension and angina"),
        ),
        PdbLigandSpec("7BU7", "P0G", "ADRB1 orthosteric antagonist pocket"),
    ),
    TargetSpec(
        "TGT-HMGCR",
        "HMGCR",
        ("HMG-CoA reductase",),
        "P04035",
        "cardiovascular",
        "enzyme",
        "HMG-CoA reductase active-site inhibition with statin acid pharmacophore",
        "Myopathy, CYP/OATP transport interactions, and hepatic monitoring",
        (
            DrugSpec("atorvastatin", "approved", "HMG-CoA reductase inhibitor", "Hypercholesterolemia and cardiovascular risk reduction"),
            DrugSpec("rosuvastatin", "approved", "HMG-CoA reductase inhibitor", "Hypercholesterolemia and cardiovascular risk reduction"),
            DrugSpec("simvastatin", "approved", "HMG-CoA reductase inhibitor prodrug", "Hypercholesterolemia and cardiovascular risk reduction"),
        ),
        PdbLigandSpec("1HW9", "SIM", "HMG-CoA reductase statin-binding pocket"),
    ),
    TargetSpec(
        "TGT-NMDA",
        "NMDA receptor",
        ("GRIN1", "NMDAR"),
        "Q05586",
        "neurology",
        "ion_channel",
        "Ion-channel or ligand-binding modulation with subtype awareness",
        "CNS exposure, psychotomimetic effects, and ion-channel selectivity",
        (
            DrugSpec("memantine", "approved", "Uncompetitive NMDA receptor antagonist", "Alzheimer disease"),
            DrugSpec("ketamine", "approved", "NMDA receptor antagonist", "Anesthesia and treatment-resistant depression"),
            DrugSpec("dextromethorphan", "approved", "NMDA receptor antagonist and sigma receptor ligand", "Cough and neuropsychiatric combinations"),
        ),
        PdbLigandSpec("5H8H", "5YC", "NMDA receptor ligand-binding/modulator site"),
    ),
    TargetSpec(
        "TGT-AMPA",
        "AMPA receptor",
        ("GRIA2", "AMPAR"),
        "P42262",
        "neurology",
        "ion_channel",
        "AMPA receptor negative or positive allosteric modulation",
        "CNS adverse effects, seizure threshold, and subtype selectivity",
        (
            DrugSpec("perampanel", "approved", "Noncompetitive AMPA receptor antagonist", "Epilepsy"),
            DrugSpec("talampanel", "clinical", "AMPA receptor antagonist", "Epilepsy and neurodegeneration studies"),
            DrugSpec("CX516", "clinical", "AMPA receptor positive allosteric modulator", "Cognitive disorder studies"),
        ),
        PdbLigandSpec("2XHD", "7T9", "AMPA receptor allosteric antagonist pocket"),
    ),
    TargetSpec(
        "TGT-MGLUR5",
        "mGluR5",
        ("GRM5", "metabotropic glutamate receptor 5"),
        "P41594",
        "neurology",
        "gpcr",
        "Negative allosteric modulation of class C GPCR transmembrane pocket",
        "CNS exposure, psychiatric tolerability, and glutamate receptor selectivity",
        (
            DrugSpec("mavoglurant", "clinical", "mGluR5 negative allosteric modulator", "Fragile X and Parkinson disease dyskinesia studies"),
            DrugSpec("basimglurant", "clinical", "mGluR5 negative allosteric modulator", "Depression and fragile X studies"),
            DrugSpec("fenobam", "clinical", "mGluR5 negative allosteric modulator", "Anxiety and fragile X studies"),
        ),
        PdbLigandSpec("4OO9", "2U8", "mGluR5 transmembrane allosteric pocket"),
    ),
    TargetSpec(
        "TGT-HTR1A",
        "5-HT1A",
        ("HTR1A", "serotonin 1A receptor"),
        "P08908",
        "neurology",
        "gpcr",
        "Serotonin 1A orthosteric agonism/partial agonism",
        "CNS exposure, serotonergic adverse effects, and receptor subtype selectivity",
        (
            DrugSpec("buspirone", "approved", "5-HT1A partial agonist", "Anxiety disorders"),
            DrugSpec("vilazodone", "approved", "SSRI and 5-HT1A partial agonist", "Major depressive disorder"),
            DrugSpec("tandospirone", "approved", "5-HT1A partial agonist", "Anxiety disorders"),
        ),
        PdbLigandSpec("7E2Z", "9SC", "5-HT1A orthosteric pocket"),
    ),
    TargetSpec(
        "TGT-HTR2A",
        "5-HT2A",
        ("HTR2A", "serotonin 2A receptor"),
        "P28223",
        "neurology",
        "gpcr",
        "Serotonin 2A orthosteric antagonism/inverse agonism",
        "CNS exposure, QT/hERG risk, and serotonergic subtype selectivity",
        (
            DrugSpec("pimavanserin", "approved", "5-HT2A inverse agonist/antagonist", "Parkinson disease psychosis"),
            DrugSpec("risperidone", "approved", "D2 and 5-HT2A antagonist", "Schizophrenia and bipolar disorder"),
            DrugSpec("ketanserin", "tool", "5-HT2A antagonist", "Serotonin receptor pharmacology"),
        ),
        PdbLigandSpec("6A93", "8NU", "5-HT2A orthosteric pocket"),
    ),
    TargetSpec(
        "TGT-DRD2",
        "DRD2",
        ("D2 dopamine receptor", "dopamine D2 receptor"),
        "P14416",
        "neurology",
        "gpcr",
        "D2 receptor antagonism or partial agonism with D3/5-HT selectivity context",
        "EPS, prolactin elevation, metabolic risk, and QT/hERG liability",
        (
            DrugSpec("haloperidol", "approved", "D2 dopamine receptor antagonist", "Schizophrenia and acute psychosis"),
            DrugSpec("risperidone", "approved", "D2 and 5-HT2A antagonist", "Schizophrenia and bipolar disorder"),
            DrugSpec("aripiprazole", "approved", "D2 partial agonist", "Schizophrenia and bipolar disorder"),
        ),
        PdbLigandSpec("6CM4", "8NU", "DRD2 orthosteric pocket"),
    ),
    TargetSpec(
        "TGT-MAOB",
        "MAO-B",
        ("MAOB", "monoamine oxidase B"),
        "P27338",
        "neurology",
        "enzyme",
        "FAD-dependent monoamine oxidase B inhibition",
        "CNS exposure, tyramine/serotonergic interaction risk, and MAO-A selectivity",
        (
            DrugSpec("selegiline", "approved", "Irreversible MAO-B inhibitor", "Parkinson disease"),
            DrugSpec("rasagiline", "approved", "Irreversible MAO-B inhibitor", "Parkinson disease"),
            DrugSpec("safinamide", "approved", "Reversible MAO-B inhibitor", "Parkinson disease"),
        ),
        PdbLigandSpec("28WL", "A1JF0", "MAO-B inhibitor cavity"),
    ),
    TargetSpec(
        "TGT-ACHE",
        "AChE",
        ("ACHE", "acetylcholinesterase"),
        "P22303",
        "neurology",
        "enzyme",
        "Catalytic gorge cholinesterase inhibition with peripheral-site awareness",
        "Cholinergic GI/cardiac effects and butyrylcholinesterase selectivity",
        (
            DrugSpec("donepezil", "approved", "Acetylcholinesterase inhibitor", "Alzheimer disease dementia"),
            DrugSpec("rivastigmine", "approved", "Acetylcholinesterase and butyrylcholinesterase inhibitor", "Alzheimer and Parkinson disease dementia"),
            DrugSpec("galantamine", "approved", "Acetylcholinesterase inhibitor and nicotinic modulator", "Alzheimer disease dementia"),
        ),
        PdbLigandSpec("4BDT", "HUW", "AChE catalytic gorge"),
    ),
    TargetSpec(
        "TGT-BACE1",
        "BACE1",
        ("beta-secretase 1", "beta-site APP cleaving enzyme 1"),
        "P56817",
        "neurology",
        "protease",
        "Aspartyl protease active-site inhibition with CNS penetration constraints",
        "CNS safety, high polarity/permeability tension, and off-target aspartyl proteases",
        (
            DrugSpec("verubecestat", "clinical", "BACE1 inhibitor", "Alzheimer disease studies"),
            DrugSpec("lanabecestat", "clinical", "BACE1 inhibitor", "Alzheimer disease studies"),
            DrugSpec("atabecestat", "clinical", "BACE1 inhibitor", "Alzheimer disease studies"),
        ),
        PdbLigandSpec("1TQF", "32P", "BACE1 aspartyl protease active site"),
    ),
    TargetSpec(
        "TGT-HIV1-PROTEASE",
        "HIV-1 protease",
        ("HIV PR", "HIV-1 gag-pol protease"),
        "P04585",
        "infectious",
        "protease",
        "Viral aspartyl protease active-site inhibition with resistance mutation coverage",
        "CYP3A4 boosting/DDI burden, lipodystrophy signals, and resistance barrier",
        (
            DrugSpec("darunavir", "approved", "HIV-1 protease inhibitor", "HIV infection"),
            DrugSpec("atazanavir", "approved", "HIV-1 protease inhibitor", "HIV infection"),
            DrugSpec("lopinavir", "approved", "HIV-1 protease inhibitor", "HIV infection"),
        ),
        PdbLigandSpec("1BV7", "XV6", "HIV-1 protease active site"),
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Expand built-in target/drug knowledge from curated target specs.")
    parser.add_argument("--offline", action="store_true", help="Use cached PubChem/PDB data only.")
    parser.add_argument("--skip-pdb", action="store_true", help="Do not fetch or compute PDB ligand binding boxes.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of new target specs for debugging.")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PDB_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    existing = json.loads(TARGET_LIBRARY.read_text(encoding="utf-8"))
    by_id = {target["target_id"]: target for target in existing}
    pubchem_cache = load_json(PUBCHEM_CACHE, {})
    warnings: list[str] = []

    specs = TARGET_SPECS[: args.limit] if args.limit else TARGET_SPECS
    for spec in specs:
        by_id[spec.target_id] = build_target_payload(
            spec,
            pubchem_cache=pubchem_cache,
            warnings=warnings,
            offline=args.offline,
            skip_pdb=args.skip_pdb,
        )

    expanded = [by_id[target["target_id"]] for target in existing if target["target_id"] in by_id]
    existing_ids = {target["target_id"] for target in existing}
    expanded.extend(by_id[spec.target_id] for spec in specs if spec.target_id not in existing_ids)

    TARGET_LIBRARY.write_text(json.dumps(expanded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PUBCHEM_CACHE.write_text(json.dumps(pubchem_cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    drug_count = sum(len(target.get("drugs", [])) for target in expanded)
    site_count = sum(len(target.get("binding_sites", [])) for target in expanded)
    print(f"Wrote {len(expanded)} targets, {drug_count} drugs, {site_count} binding sites to {TARGET_LIBRARY}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    return 0


def build_target_payload(
    spec: TargetSpec,
    *,
    pubchem_cache: dict[str, Any],
    warnings: list[str],
    offline: bool,
    skip_pdb: bool,
) -> dict[str, Any]:
    pdb_ids = list(dict.fromkeys(([spec.pdb_ligand.pdb_id] if spec.pdb_ligand else []) + list(spec.extra_pdb_ids)))
    binding_sites: list[dict[str, Any]] = []
    if spec.pdb_ligand and not skip_pdb:
        try:
            site = build_binding_site(spec, spec.pdb_ligand, offline=offline)
            if site:
                binding_sites.append(site)
        except Exception as exc:
            warnings.append(f"{spec.target_id}:{spec.pdb_ligand.pdb_id}:{exc}")

    drugs = [
        build_drug_payload(drug, spec.target_id, pubchem_cache=pubchem_cache, warnings=warnings, offline=offline)
        for drug in spec.drugs
    ]
    return {
        "target_id": spec.target_id,
        "name": spec.name,
        "aliases": list(spec.aliases),
        "uniprot_id": spec.uniprot_id,
        "species": "Homo sapiens",
        "pdb_ids": pdb_ids,
        "pocket_summary": pocket_summary(spec, binding_sites),
        "summary": target_summary(spec),
        "drugs": drugs,
        "binding_sites": binding_sites,
        "sar_rules": sar_rules(spec),
        "admet_risks": admet_risks(spec),
        "external_refs": {
            "uniprot": f"https://www.uniprot.org/uniprotkb/{spec.uniprot_id}/entry",
            "rcsb": [f"https://www.rcsb.org/structure/{pdb_id}" for pdb_id in pdb_ids],
        },
    }


def build_drug_payload(
    drug: DrugSpec,
    target_id: str,
    *,
    pubchem_cache: dict[str, Any],
    warnings: list[str],
    offline: bool,
) -> dict[str, Any]:
    properties = fetch_pubchem_properties(drug.name, pubchem_cache, offline=offline)
    if not properties:
        warnings.append(f"{target_id}:{drug.name}:pubchem_not_found")
        properties = {}
    canonical_smiles = properties.get("CanonicalSMILES") or properties.get("ConnectivitySMILES") or properties.get("SMILES")
    isomeric_smiles = properties.get("IsomericSMILES") or properties.get("SMILES") or canonical_smiles
    cid = properties.get("CID")
    return {
        "drug_name": drug.name,
        "drug_status": drug.status,
        "mechanism": drug.mechanism,
        "indication": drug.indication,
        "smiles": canonical_smiles,
        "canonical_smiles": canonical_smiles,
        "isomeric_smiles": isomeric_smiles,
        "inchi_key": properties.get("InChIKey"),
        "pubchem_cid": cid,
        "evidence_source": "PubChem PUG-REST + curated target expansion (2026-07-13)",
        "external_refs": {
            "pubchem": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}" if cid else None,
            "target_id": target_id,
        },
    }


def fetch_pubchem_properties(name: str, cache: dict[str, Any], *, offline: bool) -> dict[str, Any] | None:
    key = name.lower()
    if key in cache:
        return cache[key]
    if offline:
        return None
    fields = ",".join(
        [
            "SMILES",
            "ConnectivitySMILES",
            "CanonicalSMILES",
            "IsomericSMILES",
            "InChIKey",
            "MolecularFormula",
            "MolecularWeight",
            "ExactMass",
        ]
    )
    url = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
        f"{urllib.parse.quote(name)}/property/{fields}/JSON"
    )
    payload = fetch_json(url)
    properties = (payload.get("PropertyTable") or {}).get("Properties") or []
    if not properties:
        return None
    cache[key] = properties[0]
    time.sleep(0.15)
    return cache[key]


def build_binding_site(spec: TargetSpec, pdb_spec: PdbLigandSpec, *, offline: bool) -> dict[str, Any] | None:
    cif_text = fetch_pdb_cif(pdb_spec.pdb_id, offline=offline)
    atoms = parse_mmcif_atoms(cif_text)
    ligand_atoms_by_instance: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    ligand_code = pdb_spec.ligand.upper()
    for atom in atoms:
        if atom.get("group_PDB") != "HETATM":
            continue
        if (atom.get("auth_comp_id") or atom.get("label_comp_id") or "").upper() != ligand_code:
            continue
        if is_hydrogen(atom):
            continue
        key = (
            atom.get("auth_comp_id") or atom.get("label_comp_id") or ligand_code,
            atom.get("auth_asym_id") or atom.get("label_asym_id") or "?",
            atom.get("auth_seq_id") or atom.get("label_seq_id") or "?",
        )
        ligand_atoms_by_instance[key].append(atom)

    if not ligand_atoms_by_instance:
        return None
    instance_key, ligand_atoms = max(ligand_atoms_by_instance.items(), key=lambda item: len(item[1]))
    center, size = ligand_box(ligand_atoms, padding=8.0)
    residues = nearby_residues(atoms, ligand_atoms)
    reference_ligand = " ".join(str(part) for part in instance_key)
    return {
        "binding_site_id": f"SITE-{spec.target_id}-{pdb_spec.pdb_id}",
        "site_name": pdb_spec.site_name,
        "pdb_id": pdb_spec.pdb_id,
        "reference_ligand": reference_ligand,
        "source_url": f"https://www.rcsb.org/structure/{pdb_spec.pdb_id}",
        "grid_box": {
            "center": center,
            "size": size,
            "unit": "angstrom",
            "method": "RCSB ligand heavy-atom bounding box with 8 A padding",
        },
        "key_residues": residues,
    }


def fetch_pdb_cif(pdb_id: str, *, offline: bool) -> str:
    cache_path = PDB_CACHE_DIR / f"{pdb_id.upper()}.cif"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="ignore")
    if offline:
        raise FileNotFoundError(f"missing cached PDB CIF for {pdb_id}")
    url = f"https://files.rcsb.org/download/{pdb_id.upper()}.cif"
    with urllib.request.urlopen(url, timeout=30) as response:
        text = response.read().decode("utf-8", errors="ignore")
    cache_path.write_text(text, encoding="utf-8")
    time.sleep(0.15)
    return text


def parse_mmcif_atoms(cif_text: str) -> list[dict[str, Any]]:
    lines = cif_text.splitlines()
    atoms: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() != "loop_":
            i += 1
            continue
        i += 1
        headers: list[str] = []
        while i < len(lines) and lines[i].startswith("_atom_site."):
            headers.append(lines[i].strip().removeprefix("_atom_site."))
            i += 1
        if not headers:
            continue
        while i < len(lines):
            line = lines[i].strip()
            if not line or line == "#" or line.startswith("_") or line == "loop_":
                break
            try:
                values = shlex.split(line)
            except ValueError:
                i += 1
                continue
            if len(values) >= len(headers):
                atom = dict(zip(headers, values, strict=False))
                try:
                    atom["Cartn_x"] = float(atom["Cartn_x"])
                    atom["Cartn_y"] = float(atom["Cartn_y"])
                    atom["Cartn_z"] = float(atom["Cartn_z"])
                    atoms.append(atom)
                except (KeyError, TypeError, ValueError):
                    pass
            i += 1
    return atoms


def ligand_box(ligand_atoms: list[dict[str, Any]], *, padding: float) -> tuple[list[float], list[float]]:
    xs = [float(atom["Cartn_x"]) for atom in ligand_atoms]
    ys = [float(atom["Cartn_y"]) for atom in ligand_atoms]
    zs = [float(atom["Cartn_z"]) for atom in ligand_atoms]
    mins = [min(xs), min(ys), min(zs)]
    maxs = [max(xs), max(ys), max(zs)]
    center = [round((lo + hi) / 2.0, 3) for lo, hi in zip(mins, maxs, strict=True)]
    size = [round((hi - lo) + padding, 3) for lo, hi in zip(mins, maxs, strict=True)]
    return center, size


def nearby_residues(atoms: list[dict[str, Any]], ligand_atoms: list[dict[str, Any]], cutoff: float = 5.0) -> list[str]:
    ligand_xyz = [(atom["Cartn_x"], atom["Cartn_y"], atom["Cartn_z"]) for atom in ligand_atoms]
    residue_distances: dict[str, float] = {}
    for atom in atoms:
        if atom.get("group_PDB") != "ATOM" or is_hydrogen(atom):
            continue
        x, y, z = atom["Cartn_x"], atom["Cartn_y"], atom["Cartn_z"]
        best = min(distance((x, y, z), xyz) for xyz in ligand_xyz)
        if best > cutoff:
            continue
        residue = atom.get("auth_comp_id") or atom.get("label_comp_id") or "UNK"
        chain = atom.get("auth_asym_id") or atom.get("label_asym_id") or "?"
        seq = atom.get("auth_seq_id") or atom.get("label_seq_id") or "?"
        label = f"{residue}{seq}:{chain}"
        residue_distances[label] = min(best, residue_distances.get(label, 999.0))
    return [label for label, _ in sorted(residue_distances.items(), key=lambda item: (item[1], item[0]))[:24]]


def is_hydrogen(atom: dict[str, Any]) -> bool:
    symbol = (atom.get("type_symbol") or atom.get("label_atom_id") or "").upper()
    return symbol.startswith("H") or symbol.startswith("D")


def distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def target_summary(spec: TargetSpec) -> str:
    aliases = ", ".join(spec.aliases)
    return (
        f"{spec.name} ({aliases}) is a {spec.area} target in the {spec.family} class. "
        f"The built-in expansion profile focuses on {spec.design_focus}. "
        f"Representative ligands include {', '.join(drug.name for drug in spec.drugs)}. "
        f"Design reviews should track {spec.safety_focus}."
    )


def pocket_summary(spec: TargetSpec, binding_sites: list[dict[str, Any]]) -> str:
    if binding_sites:
        site = binding_sites[0]
        return (
            f"{site['site_name']} represented by PDB {site['pdb_id']} ligand "
            f"{site['reference_ligand']}."
        )
    return (
        f"No curated ligand-derived docking box was selected for {spec.name} in this batch; "
        "use an experimental complex or AlphaFold/P2Rank workflow before structure-based docking."
    )


def sar_rules(spec: TargetSpec) -> list[dict[str, Any]]:
    prefix = spec.target_id.removeprefix("TGT-").replace("-", "")
    base = [
        {
            "rule_id": f"{prefix}-SAR-001",
            "title": f"Preserve the primary {spec.family} pharmacophore",
            "rationale": f"{spec.name} optimization is driven by {spec.design_focus}.",
            "preferred_change": "Modify solvent-exposed or peripheral vectors before replacing the core recognition motif.",
            "avoid": "Changing the main binding motif without a replacement interaction hypothesis.",
            "evidence_level": "curated expansion",
        },
        {
            "rule_id": f"{prefix}-SAR-002",
            "title": "Annotate selectivity and resistance hypotheses",
            "rationale": f"Design decisions for {spec.name} should be interpreted against target-family selectivity and known clinical liabilities.",
            "preferred_change": "Record the intended selectivity vector and resistance coverage for each core change.",
            "avoid": "Ranking candidates only by a single docking or similarity score.",
            "evidence_level": "curated expansion",
        },
    ]
    if spec.family in {"kinase", "kinase_allosteric"}:
        base.append(
            {
                "rule_id": f"{prefix}-SAR-003",
                "title": "Balance hinge/allosteric potency with kinase panel risk",
                "rationale": "Kinase ATP pockets are conserved and off-target kinase activity can dominate safety margins.",
                "preferred_change": "Tune back-pocket and solvent-channel substituents while tracking family selectivity.",
                "avoid": "Adding aromatic bulk that increases promiscuity without selectivity evidence.",
                "evidence_level": "curated expansion",
            }
        )
    elif spec.family == "gpcr":
        base.append(
            {
                "rule_id": f"{prefix}-SAR-003",
                "title": "Treat receptor subtype selectivity as a first-class endpoint",
                "rationale": "GPCR orthosteric pockets can be conserved across subtypes.",
                "preferred_change": "Use polar and shape vectors that are supported by subtype pocket differences.",
                "avoid": "Increasing basic lipophilicity solely to improve apparent potency.",
                "evidence_level": "curated expansion",
            }
        )
    return base


def admet_risks(spec: TargetSpec) -> list[dict[str, Any]]:
    prefix = spec.target_id.removeprefix("TGT-").replace("-", "")
    risks = [
        {
            "risk_id": f"{prefix}-ADMET-001",
            "category": "target-class safety",
            "signal": spec.safety_focus,
            "mitigation": "Carry the target-specific safety note into candidate ranking and self-refutation.",
            "severity": "medium",
        },
        {
            "risk_id": f"{prefix}-ADMET-002",
            "category": "developability",
            "signal": "Representative active drugs can be large, aromatic, basic, peptide-like, or highly polar depending on target class.",
            "mitigation": "Track logP/TPSA/MW, ionization, CYP/P-gp flags, and route-of-administration assumptions together.",
            "severity": "medium",
        },
    ]
    if spec.family in {"kinase", "gpcr"}:
        risks.append(
            {
                "risk_id": f"{prefix}-ADMET-003",
                "category": "cardiotoxicity",
                "signal": "Basic lipophilic motifs and high aromaticity can increase hERG/QT concern.",
                "mitigation": "Penalize high cLogP plus basic amine count and flag hERG predictions early.",
                "severity": "medium",
            }
        )
    return risks


def fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
