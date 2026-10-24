"""Single slice x dictionary-group entry; shares the existing evidence workflow."""
import json
import threading
from pathlib import Path
import full_dictionary_supplement_v92 as core


class ScopedApiRunner(core.ApiRunner):
    """Enforce scope before sending, and record non-secret request diagnostics."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.scope_lock=threading.Lock();self.scope_count=0;self.scans=0

    def call(self,system,payload,doc,phase,response_schema=None):
        scoped=payload.get('request_scope')=='single_unit'
        if scoped:
            uid=payload['target_unit_id']
            for name in ['audit_units','target_units','requested_units']:
                if name in payload:
                    assert len(payload[name])==1 and payload[name][0]['unit_id']==uid,'Mixed target units blocked before API'
                    assert payload['source_text']==payload[name][0]['text'],'Full source in single-unit request blocked'
            for name in ['candidates','rejected_facts','unresolved_facts','repair_candidates','existing_pairs','drafts']:
                assert all(x['unit_id']==uid for x in payload.get(name,[])), 'Another unit leaked into the request'
            metadata={'request_scope':'single_unit','target_unit_id':uid,'target_unit_count':1,
                'target_chars':len(payload['source_text']),
                'identity_context_chars':sum(len(e['text']) for e in payload.get('identity_context',[])),
                'branch_label_count':len(payload.get('all_branch_labels',[])),
                'candidate_definition_count':len(payload.get('candidate_definitions',[]))}
            assert metadata['identity_context_chars']<=1200,'Context budget exceeded'
            assert metadata['branch_label_count']<=48,'Dictionary branch too large'
        else:
            # Existing project repair is identity-only; it does not select labels.
            assert not phase.startswith('紧凑'),'Unscoped label/rewrite request blocked'
            metadata={'request_scope':'identity_only','target_unit_count':None}
        raw,metrics=super().call(system,payload,doc,phase,response_schema)
        metrics.update(metadata)
        cache=self.output/'calls'/(metrics['request_key']+'.json')
        core.save_json(cache,{'response':raw,'metrics':metrics})
        with self.scope_lock:
            self.scope_count+=int(scoped);self.scans+=int(phase.startswith('紧凑单片全字典查漏-v93-'))
            if self.scope_count%50==0:
                report={'single_unit_requests':self.scope_count,'completed_scan_requests':self.scans,
                    'latest_source':doc['record_id'],'latest_status':metrics['status']}
                core.save_json(self.output/'single_unit_progress.json',report)
                print(json.dumps(report,ensure_ascii=False),flush=True)
        return raw,metrics


if __name__=='__main__':
    core.main(default_request_mode='single_unit',runner_class=ScopedApiRunner)
