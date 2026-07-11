$urls = @(
    'https://rest.uniprot.org/uniprotkb/P00533.json',
    'https://www.ebi.ac.uk/chembl/api/data/target/CHEMBL203.json',
    'https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/gefitinib/property/CanonicalSMILES/JSON',
    'https://data.rcsb.org/rest/v1/core/entry/1M17',
    'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=EGFR+inhibitor&retmode=json&retmax=1',
    'https://api.fda.gov/drug/label.json?search=openfda.generic_name:%22GEFITINIB%22&limit=1'
)
foreach ($url in $urls) {
    try {
        $r = Invoke-WebRequest -Uri $url -Method Head -TimeoutSec 15 -UseBasicParsing
        Write-Output "$($r.StatusCode) $url"
    } catch {
        Write-Output "FAIL $url : $($_.Exception.Message)"
    }
}
