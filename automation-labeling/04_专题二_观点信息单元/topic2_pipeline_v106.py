"""Current T2 entry: existing slicing/tagging -> project binding -> own scores.

Use prepare_export(payload, scored_records) before the existing Excel exporter.
Old label, project and call checkpoints are never rewritten.
"""
import copy
import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'support/comment-project-binding'))
import comment_pipeline_v105 as legacy
import slice_sentiment_v107 as sentiment
_output=None

def configure(output_dir):
 global _output
 _output=Path(output_dir);legacy.configure(_output)
 legacy.q.p.OUT=_output;legacy.q.p.v.OUT=_output
 legacy.q.p.STOP=_output/'control/soft_stop.request'

def create_runner(concurrency=2):
 if _output is None:raise RuntimeError('Call configure(output_dir) first')
 return legacy.q.p.configure_runner(concurrency,True)

def _score(source,runner,proof):
 if _output is None:raise RuntimeError('Call configure(output_dir) first')
 scored=sentiment.attach(source,runner,_output)
 path=_output/'sentiment_sources'/(sentiment.digest([source['record_id'],scored['slice_sentiment']])+'.json')
 sentiment.save(path,scored)
 return scored,{'project':proof,'sentiment':{'file':str(path),'sha256':sentiment.sha(path),'version':sentiment.VERSION}}

def process_saved(source,runner,force_revision=False):
 original=copy.deepcopy(source);original.pop('slice_sentiment',None)
 revised,proof=legacy.process_saved(original,runner,force_revision)
 return _score(revised,runner,proof)

def process_document(doc,taxonomy,projects,origins,prior,runner):
 revised,proof=legacy.process_document(doc,taxonomy,projects,origins,prior,runner)
 if revised['state']=='retry_required':return revised,proof
 return _score(revised,runner,proof)

def score_completed(source,runner):
 """Existing validated labels/projects need ONLY the new scoring stage."""
 return _score(source,runner,None)

def prepare_export(payload,scored_records):
 from topic2_heat_v110 import refresh_payload_heat
 return refresh_payload_heat(sentiment.rescore_payload(payload,scored_records))

def aggregate(scored_records,taxonomy,projects,parent_heats=None,ad_decisions=None,*,heat_baseline_files=None):
 """New exports need no legacy score, even when the CSV score is absent."""
 from topic2_metrics_v106 import aggregate as build
 return build(scored_records,taxonomy,projects,parent_heats,ad_decisions,sentiment_engine=sentiment,heat_baseline_files=heat_baseline_files)

def export_workbook(payload,output_path,**kwargs):
 """Final output follows the authorized nine-sheet v111 delivery contract."""
 from topic2_delivery_v108 import export_workbook as export
 return export(payload,output_path,**kwargs)
