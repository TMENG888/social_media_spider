"""Opt-in v76 + fail-closed adjacent consolidation, shared runner."""
import delivery_v76 as baseline
import delivery_v11 as pipeline
from semantic_merge_v77 import consolidate

def process_document(doc,taxonomy,business,runner):
    return consolidate(baseline.process_document(doc,taxonomy,business,runner),runner)

def activate():
    baseline.activate()
    pipeline.process_document=process_document
    pipeline.VERSION='delivery-v76.4-merge-v77.2-20261010'
    pipeline.IMPLEMENTATION_FILES=list(dict.fromkeys(pipeline.IMPLEMENTATION_FILES+['semantic_merge_v77.py','delivery_v77.py']))

if __name__=='__main__':
    activate()
    pipeline.main()
