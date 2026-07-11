CREATE EXTENSION IF NOT EXISTS vector;

-- RDKit cartridge is recommended by the product spec. The pgvector image used for
-- local development does not bundle it, so molecule chemistry is designed to run
-- through isolated tool adapters until a combined Postgres image is selected.
-- CREATE EXTENSION IF NOT EXISTS rdkit;
