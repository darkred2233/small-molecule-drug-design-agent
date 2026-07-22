# BRAF V600E 3OG7 Binding-Site Record

## Primary source

- RCSB PDB entry: [3OG7](https://www.rcsb.org/structure/3OG7)
- RCSB PDB Core API entry record: `https://data.rcsb.org/rest/v1/core/entry/3OG7`
- RCSB PDB coordinate download: `https://files.rcsb.org/download/3OG7.pdb`

The entry record identifies 3OG7 as an X-ray structure titled "B-Raf Kinase
V600E oncogenic mutant in complex with PLX4032". Its non-polymer entity `2`
is PDB component `032`, the co-crystallized PLX4032 ligand.

## Pocket calculation

The project record uses the official 3OG7 coordinates. It selects all 33
`HETATM` coordinates for component `032`, chain `A`, residue `1` and calculates
the ligand bounding box. The docking grid center is the midpoint of that box;
each grid dimension is the ligand extent plus 12 Angstrom, with a minimum of
18 Angstrom.

- Grid center: `[2.643, -2.280, -19.403]` Angstrom
- Grid size: `[28.305, 18.000, 18.396]` Angstrom
- Contact residues: protein residues with at least one atom within 5 Angstrom
  of component `032`

This is a co-crystal-derived starting grid for BRAF V600E screening. It is not
a substitute for reviewing protonation, alternate conformations, and the
binding-site definition before a production docking campaign.
