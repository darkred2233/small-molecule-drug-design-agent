import time
from medagent.core.config import get_settings
from medagent.db.session import build_session_factory
from medagent.db.models import Project
from medagent.services.rag_collection import collect_and_index_project_packs

settings = get_settings()
sf = build_session_factory(settings)

targets_to_process = [
    'TGT-EGFR', 'TGT-ALK', 'TGT-BRAF', 'TGT-KRAS-G12C', 'TGT-JAK2',
    'TGT-BTK', 'TGT-CDK4-6', 'TGT-PARP1', 'TGT-PI3K', 'TGT-HDAC'
]

for target_id in targets_to_process:
    db = sf()
    project = db.query(Project).filter_by(target_id=target_id).first()
    if not project:
        print(f'No project for {target_id}')
        continue
    
    print(f'Processing {target_id}...')
    try:
        result = collect_and_index_project_packs(db, settings, project)
        db.commit()
        doc_count = result.get('document_count', 0)
        chunk_count = result.get('chunk_count', 0)
        print(f'  Done: {doc_count} docs, {chunk_count} chunks')
    except Exception as e:
        print(f'  Error: {e}')
    finally:
        db.close()
    
    time.sleep(2)

print('All done!')
