# Data Expansion Research Sources for Target-Centric RAG

Date checked: 2026-07-13

Scope: public or low-friction sources for collecting literature abstracts and patent summaries for small-molecule, target-centric drug design RAG. This note focuses on sources that can be used without credentials, or that expose public endpoints but may require a free key or public cloud account for production-scale use.

## Bottom Line

Use **PubMed through NCBI E-utilities** and **Europe PMC** as the primary paper-abstract sources. PubMed is the canonical biomedical citation source; Europe PMC is often the easiest JSON source for abstracts, full-text links, open-access flags, and citation counts.

Use **USPTO Open Data Portal bulk full-text XML** as the default U.S. patent-text source, then enrich patent chemistry with **SureChEMBL** compound-patent links where available. Treat **PatentsView**, **OpenAlex**, **Crossref**, and **Google Patents BigQuery** as enrichment layers, not primary no-credential abstract/summary sources.

For RAG, index concise evidence records: paper abstracts and curated snippets; patent title/abstract, independent-claim summaries, target/mechanism snippets, examples/assay summaries, and compound-patent links. Preserve source IDs, retrieval dates, and license/terms metadata for every chunk.

## Source Comparison

| Source | Best Use | Access Notes | Practical Notes |
| --- | --- | --- | --- |
| NCBI PubMed E-utilities | Canonical PMID discovery and PubMed XML abstracts | No key required at <=3 requests/sec; API key raises default limit to 10 requests/sec. Include `tool` and `email`. | Use `ESearch` for PMIDs, `usehistory=y` for batches, `EFetch` with `retmode=xml` for abstracts and IDs. Official docs: [E-utilities intro](https://www.ncbi.nlm.nih.gov/books/NBK25497/), [parameters](https://www.ncbi.nlm.nih.gov/books/NBK25499/), [NCBI API page](https://www.ncbi.nlm.nih.gov/home/develop/api/). |
| Europe PMC Articles REST API | Convenient JSON metadata, abstracts, OA/full-text links, citation counts | Public REST endpoint. | Use `resultType=core` for full metadata including `abstractText`, `fullTextUrlList`, `pmid`, `pmcid`, and `doi`; page with `cursorMark`. Docs: [Europe PMC RESTful Web Service](https://europepmc.org/RestfulWebService). |
| Crossref REST API | DOI metadata, publisher bibliographic fields, license links, de-duplication | Public API; use polite behavior and `mailto`. | Search can be noisy and abstracts are deposited inconsistently, often with markup. Use for DOI enrichment rather than primary abstracts. Docs: [Crossref REST tips](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/) and [API root](https://api.crossref.org/). |
| OpenAlex | Citation graph, OA status, DOI/PMID mapping, topic enrichment | Public, but current docs indicate production-scale API use needs a free API key and a daily free allowance; unauthenticated calls may only be suitable for demos. | Works may include `abstract_inverted_index`, not plain text, due to legal constraints. Prefer PubMed/Europe PMC for abstracts. Docs: [OpenAlex overview](https://developers.openalex.org/), [authentication](https://developers.openalex.org/api-reference/authentication), [works](https://developers.openalex.org/api-reference/works), [work object abstract field](https://github.com/ourresearch/openalex-docs/blob/main/api-entities/works/work-object/README.md). |
| USPTO Open Data Portal bulk XML | U.S. patent grants/applications full text: title, abstract, claims, description, examples | Public bulk downloads through ODP. API surfaces may require a USPTO.gov/ID.me API key; bulk file download URLs should be verified during implementation. | Start with "Patent Grant Full-Text Data (No Images) - XML" and "Patent Application Full-Text Data (No Images)". Parse weekly concatenated XML and DTD versions. Sources: [ODP bulk directory](https://data.uspto.gov/bulkdata), [patent grant full-text XML dataset](https://data.uspto.gov/bulkdata/datasets?f%5B0%5D=product_category%3A39180&f%5B1%5D=product_category%3A39187&f%5B2%5D=product_category%3A39193&f%5B3%5D=product_category%3A39205&f%5B4%5D=product_type%3A39167&f%5B5%5D=product_type%3A39195), [patent application full-text XML dataset](https://data.uspto.gov/bulkdata/datasets/appxml), [USPTO XML resources and DTDs](https://www.uspto.gov/learning-and-resources/xml-resources). |
| PatentsView / USPTO ODP | Normalized patent metadata, assignees, inventors, classifications, citations | PatentsView migrated into USPTO ODP starting March 20, 2026; ODP API setup requires account/key steps. | Useful for structured enrichment, not the simplest no-credential text ingestion path. Sources: [USPTO PatentsView page](https://www.uspto.gov/ip-policy/economic-research/patentsview), [PatentsView transition guide](https://data.uspto.gov/support/transition-guide/patentsview), [ODP API getting started](https://data.uspto.gov/apis/getting-started). |
| Google Patents Public Datasets on BigQuery | Large-scale patent metadata and U.S. full-text SQL analysis | Public dataset, but practical use needs a Google Cloud project and BigQuery query billing/account setup. | Good for broad landscaping and joins. Not a no-credential collector. Sources: [Google Cloud launch post](https://cloud.google.com/blog/topics/public-datasets/google-patents-public-datasets-connecting-public-paid-and-private-patent-data), [Google patents-public-data repo](https://github.com/google/patents-public-data), [dataset table docs](https://github.com/google/patents-public-data/blob/master/tables/dataset_Google%20Patents%20Public%20Datasets.md), [BigQuery public data docs](https://docs.cloud.google.com/bigquery/public-data). |
| SureChEMBL | Patent chemistry: compounds extracted from patent text/images/attachments and compound-patent mappings | Public web resource and documented bulk-data paths; current download mode should be verified before automation. | Use as a chemistry-index supplement: identify patents containing small molecules and link structures to patent sections. Not a complete patent-summary source by itself. Sources: [SureChEMBL home](https://chembl.gitbook.io/surechembl), [bulk data](https://chembl.gitbook.io/surechembl/downloads/bulk-data), [small-molecule patent filter](https://chembl.gitbook.io/surechembl/text-search/patents-with-small-molecules-filter), [EMBL-EBI SureChEMBL 2.0 note](https://www.embl.org/news/updates-from-data-resources/surechembl-2-0-is-here/). |
| Google Patents web | Human-readable validation links | Public website, but avoid scraping as a primary pipeline unless terms and robots allow it. | Store Google Patents URLs as validation links after documents are found from USPTO/SureChEMBL/BigQuery. |

## Literature Abstract Collection Workflow

1. Build target query terms from canonical target name plus aliases, for example `EGFR`, `ERBB1`, `epidermal growth factor receptor`, mutation names, and drug-class terms.
2. Discover PMIDs with NCBI `ESearch`, using `usehistory=y` for larger result sets.
3. Fetch PubMed XML in batches with `EFetch`, parse `ArticleTitle`, `Abstract/AbstractText`, `Journal`, `PublicationType`, `ArticleIdList`, `MeshHeadingList`, `ChemicalList`, and publication dates.
4. Query Europe PMC in parallel or as a second pass for convenient JSON fields such as `abstractText`, `fullTextUrlList`, `isOpenAccess`, `citedByCount`, `pubTypeList`, `pmid`, `pmcid`, and `doi`.
5. De-duplicate by DOI first, then PMID/PMCID, then normalized title plus year.
6. Optionally enrich accepted records with Crossref and OpenAlex for DOI metadata, license links, citation graph, OA route, and topic fields.

Example PubMed discovery URL:

```text
https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=((EGFR[Title/Abstract]%20OR%20ERBB1[Title/Abstract])%20AND%20(inhibitor%20OR%20ligand%20OR%20degrader%20OR%20PROTAC)%20AND%20(SAR%20OR%20%22structure%20activity%22%20OR%20selectivity%20OR%20resistance%20OR%20ADMET))&retmode=json&retmax=100&sort=relevance&usehistory=y&tool=medagent&email=YOUR_EMAIL
```

Example PubMed XML fetch:

```text
https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=41800326&retmode=xml&tool=medagent&email=YOUR_EMAIL
```

Example Europe PMC search:

```text
https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EGFR%20inhibitor%20SAR&resultType=core&pageSize=100&format=json
```

Example Crossref DOI enrichment:

```text
https://api.crossref.org/works/10.1039/d5md01113b?mailto=YOUR_EMAIL
```

Example OpenAlex DOI enrichment:

```text
https://api.openalex.org/works/https://doi.org/10.1039/d5md01113b?api_key=YOUR_KEY
```

## Patent Summary Collection Workflow

1. Start with a target-centric patent query list: target aliases, mutation names, pathway terms, modality terms, and medicinal chemistry terms.
2. Pull U.S. patent grant/application XML from USPTO ODP bulk datasets by weekly file. Parse the XML rather than scraping rendered pages.
3. Filter candidate patents by title, abstract, claims, description, CPC/IPC, and examples. For small molecules, prioritize CPC/IPC classes such as medicinal organic active ingredients and patents flagged by SureChEMBL's small-molecule filters.
4. Generate RAG summaries at the patent-family level when possible:
   - title and abstract summary
   - claimed target/mechanism summary
   - independent claim summary
   - compound-series or scaffold summary
   - examples/assay/SAR summary
   - extracted compounds or SureChEMBL IDs, if available
5. Enrich with PatentsView/ODP when credentials are available for normalized assignee, inventor, citations, and classification fields.
6. Use Google Patents links for human review, not as the default automated text source.

Example patent query pattern:

```text
("EGFR" OR "ERBB1" OR "epidermal growth factor receptor" OR "C797S")
AND (inhibitor OR modulator OR antagonist OR degrader OR PROTAC)
AND (compound OR composition OR treating OR "pharmaceutically acceptable")
```

For bulk XML parsing, preserve the source file name and document boundaries because USPTO files can contain many concatenated patent records. Use the current USPTO XML DTD page to handle version-specific fields.

## Query Templates for Target-Centric RAG

Literature:

```text
(<target aliases>)
AND (inhibitor OR ligand OR antagonist OR agonist OR modulator OR degrader OR PROTAC)
AND (SAR OR "structure activity" OR selectivity OR potency OR resistance OR ADMET OR toxicity)
```

Review-oriented literature:

```text
(<target aliases>)
AND (review OR "medicinal chemistry" OR "drug discovery")
AND (inhibitor OR ligand OR degrader OR "small molecule")
```

Patent-oriented:

```text
(<target aliases>)
AND (inhibitor OR modulator OR antagonist OR degrader OR "targeted protein degradation")
AND (compound OR composition OR method OR treating OR claim)
```

Structure-class expansion:

```text
(<target aliases>)
AND (<known scaffold> OR <reference drug> OR <series name>)
AND (analog OR derivative OR substituted OR example OR IC50 OR Ki)
```

## Provenance Fields to Store

Paper evidence:

```text
source_type: paper
source_name: pubmed | europe_pmc | crossref | openalex
pmid
pmcid
doi
europe_pmc_id
title
journal
publication_year
publication_types
abstract_text
mesh_terms
chemical_terms
source_url
retrieved_at
query_string
target_aliases_matched
license_or_terms_note
checksum
```

Patent evidence:

```text
source_type: patent
source_name: uspto_bulk_xml | patentsview | google_patents_bigquery | surechembl
publication_number
patent_number
country
kind_code
family_id_if_available
title
abstract_text
assignees
inventors
publication_date
application_date
priority_date
cpc_ipc
claims_summary
description_summary
examples_summary
assay_or_sar_summary
compound_identifiers
source_file_or_table
source_url
retrieved_at
query_string
target_aliases_matched
license_or_terms_note
not_legal_advice: true
checksum
```

## RAG Ingestion Notes

- Prefer short, attributable chunks over entire long documents. Good paper chunks are title plus abstract, conclusion/SAR snippets where licensed, and a concise target relevance note.
- For patents, avoid dumping full claims or huge compound tables directly into RAG. Summarize the independent claims, target mechanism, examples, assay conditions, and representative compounds, then link back to the patent record.
- Keep structured data outside text chunks when possible: PMIDs, DOIs, patent numbers, assignees, dates, compounds, InChIKeys, SMILES, and assay values should be structured metadata.
- Keep raw downloaded XML/JSON separately from RAG chunks if storage and licensing allow. RAG chunks should include enough provenance to re-fetch or audit the source.
- De-duplicate paper evidence by DOI/PMID and patent evidence by family/publication number. Keep multiple family members as metadata rather than near-identical text chunks.
- Log rate-limit behavior, request URLs without secret keys, response timestamps, and parser version for reproducibility.

## Caveats

- PubMed metadata access is public, but article abstracts and publisher text can still be copyrighted. Do not assume PubMed metadata equals open full text.
- Europe PMC may expose links to free or open full text, but each linked full-text license still needs to be checked before storing large verbatim passages.
- Crossref and OpenAlex are strong metadata enrichers, but neither should be treated as a complete biomedical abstract source.
- OpenAlex's current production API model uses free API keys and usage credits; unauthenticated calls may work only for limited demos.
- USPTO ODP pages and API endpoints are actively evolving after the 2026 PatentsView/ODP transition. Verify current dataset URLs and API-key requirements before implementing automated collectors.
- Google Patents BigQuery is public data, but it is not credential-free in practice because BigQuery requires a Google Cloud project and query execution context.
- SureChEMBL is excellent for chemical entity and patent linkage, but it is not a substitute for parsing patent text and claims when target-specific summaries are needed.
- Patent summaries are technical intelligence for RAG. They are not freedom-to-operate, validity, infringement, or patentability opinions.
