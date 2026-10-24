"""Offline regression contracts; no model calls or credentials required."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import full_dictionary_supplement_v92 as s


class SupplementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tax=s.base.load_taxonomy(s.DEFAULT_TAXONOMY)
        cls.prior=json.loads(s.DEFAULT_PRIOR.read_text(encoding='utf-8'))

    def fixture(self,tid='T1-2651643050694719236'):
        return copy.deepcopy(next(r for r in self.prior['results'] if r['document']['record_id']==tid))

    def test_all_topic_partitions_complete_unique(self):
        for topic,count in [(s.base.T1,323),(s.base.T2,580)]:
            idx=s.index_for(self.tax,topic);groups=s.partitions.groups(idx)
            keys=[k for g in groups for k in g['index']]
            self.assertEqual(len(keys),count);self.assertEqual(len(set(keys)),count)
            self.assertEqual(set(keys),set(idx));self.assertTrue(all(len(g['index'])<=48 for g in groups))

    def test_all_193_source_partitions_preserve_rows_and_text(self):
        for r in self.prior['results']:
            units=s.audit_units(r)
            self.assertEqual(''.join(u['text'] for u in units),r['document']['text'])
            self.assertTrue({u['unit_id'] for u in r['rows']}.issubset({u['unit_id'] for u in units}))
            if r['document']['kind']=='评论':self.assertEqual(len(units),1)

    def test_completed_row_is_still_sent_to_scanner(self):
        r=self.fixture();u=s.audit_units(r);idx=s.index_for(self.tax,s.base.T1)
        group=next(g for g in s.partitions.groups(idx) if 'D0168' in g['index'])
        def reply(system,payload,schema,doc,phase,runner):
            self.assertIn('已有标签',system);self.assertEqual(payload['source_text'],r['document']['text'])
            self.assertEqual(len(payload['audit_units']),len(u));self.assertTrue(payload['existing_pairs'])
            raw={'checked_keys':list(group['index']),'found':[],'existing_decisions':[dict(p,quotes=[],context_quotes=[],object='',reason='',confidence=1,verdict='supported') for p in payload['existing_pairs']],'unresolved_facts':[]}
            return raw,[],[],[]
        with patch.object(s,'review',reply):self.assertFalse(s.scan_branch(r,u,group,None,0)['errors'])

    def candidate(self,r,key='D0186'):
        unit=next(u for u in s.audit_units(r) if u['unit_id'].endswith('M008'))
        return dict(unit_id=unit['unit_id'],key=key,quotes=['约162㎡上叠'],context_quotes=['中海翠语・沁园下叠样板间'],object='上叠户型',reason='面积原文有据',confidence=.95)

    def test_existing_decision_schema_cannot_expand_into_other_branch_labels(self):
        r=self.fixture();units=s.audit_units(r);idx=s.index_for(self.tax,s.base.T1)
        group=next(g for g in s.partitions.groups(idx) if 'D0168' in g['index'])
        schema=s.scan_schema(group['index'],units)['properties']['existing_decisions']
        pairs=[(u['unit_id'],k) for u in units for k in u['existing_keys'] if k in group['index']]
        self.assertEqual(schema['minItems'],len(pairs));self.assertEqual(schema['maxItems'],len(pairs))
        self.assertEqual(set(schema['items']['properties']['key']['enum']),{k for uid,k in pairs})
        empty=s.scan_schema(group['index'],[dict(units[0],existing_keys=[])])['properties']['existing_decisions']
        self.assertEqual(empty['maxItems'],0)

    def test_append_multilabel_and_same_id_not_duplicated(self):
        r=self.fixture();u=s.audit_units(r);c=self.candidate(r)
        row=next(x for x in r['rows'] if x['unit_id']==c['unit_id']);trace=next(x for x in r['traces'] if x['unit_id']==c['unit_id'])
        original=copy.deepcopy(row['标签明细']);idx=s.index_for(self.tax,s.base.T1)
        unit=next(x for x in u if x['unit_id']==c['unit_id'])
        self.assertTrue(s.append_confirmed(row,trace,c,idx,r['document'],unit))
        self.assertFalse(s.append_confirmed(row,trace,c,idx,r['document'],unit))
        self.assertEqual(row['标签明细'][:-1],original)
        self.assertEqual(set(row['标签明细'][-1]),set(s.label_json(idx['D0186'])))
        self.assertIn('VOC-0186',row['打标说明'])

    def test_evidence_format_is_repaired_not_rejected(self):
        r=self.fixture();units=s.audit_units(r);c=self.candidate(r)
        c['quotes']=['约162㎡上叠……约177㎡中叠']
        audit=[];s.normalize_evidence([c],units,r['document'],audit)
        self.assertEqual(c['quotes'],['约162㎡上叠','约177㎡中叠'])
        self.assertFalse(s.evidence_errors(c,{u['unit_id']:u for u in units},s.index_for(self.tax,s.base.T1),r['document']))
        self.assertTrue(audit)

    def test_wrong_unit_evidence_is_never_borrowed(self):
        r=self.fixture();c=self.candidate(r);c['quotes']=['不存在的12米面宽']
        self.assertIn('属性证据不可逐字定位',s.evidence_errors(c,{u['unit_id']:u for u in s.audit_units(r)},s.index_for(self.tax,s.base.T1),r['document']))

    def test_history_conflict_needs_actual_resolution(self):
        r=self.fixture();c=self.candidate(r);c.update(candidate_id='C1',history_conflicts=['口径与对象不符'])
        def reply(*args):
            return {'decisions':[dict(c,verdict='supported',same_object=True,property_matches=True,modality_preserved=True,replacement_keys=[],history_condition_resolved=False,history_resolution='')]},[],[],[]
        with patch.object(s,'review',reply):
            ds,_,_,_=s.verify_candidates(r,s.audit_units(r),[c],s.index_for(self.tax,s.base.T1),None,'test')
        self.assertIn('历史拒绝必要条件未有据解释，不自动加回',ds[0]['program_issues'])

    def test_candidate_missing_response_is_not_success(self):
        r=self.fixture();c=self.candidate(r);c['candidate_id']='C1'
        with patch.object(s,'review',return_value=({'decisions':[]},[],[],[])):
            ds,_,_,err=s.verify_candidates(r,s.audit_units(r),[c],s.index_for(self.tax,s.base.T1),None,'test')
        self.assertFalse(ds);self.assertTrue(err)

    def test_alternative_receives_entire_directory_after_wrong_gift(self):
        r=self.fixture();idx=s.index_for(self.tax,s.base.T1);c=self.candidate(r,'D0188');c['replacement_keys']=['D0186']
        def reply(system,payload,*args):
            self.assertEqual({x[0] for x in payload['all_label_directory']},set(idx))
            self.assertEqual(payload['suggested_definitions'][0]['choice_key'],'D0186')
            return {'found':[self.candidate(r)],'unresolved_facts':[]},[],[],[]
        with patch.object(s,'review',reply):found,rem,_,_,err=s.alternatives(r,s.audit_units(r),[c],[],idx,None)
        self.assertEqual(found[0]['key'],'D0186');self.assertFalse(err)

    def test_alternative_api_failure_remains_visible(self):
        r=self.fixture();c=self.candidate(r)
        with patch.object(s,'review',return_value=(None,[],[],['timeout'])):
            _,remaining,_,_,err=s.alternatives(r,s.audit_units(r),[c],[],s.index_for(self.tax,s.base.T1),None)
        self.assertEqual(err,['timeout']);self.assertTrue(remaining)

    def test_non_applicable_label_is_not_allowed(self):
        r=self.fixture();c=self.candidate(r,'D0148')
        self.assertIn('未知或非本专题标签',s.evidence_errors(c,{u['unit_id']:u for u in s.audit_units(r)},s.index_for(self.tax,s.base.T1),r['document']))

    def test_failed_restore_does_not_add_empty_main_row(self):
        r=self.fixture();units=s.audit_units(r);target=next(x for x in units if x['previous_location']!='主表')
        c=self.candidate(r);c['unit_id']=target['unit_id']
        with patch.object(s,'review',return_value=(None,[],[],['timeout'])):
            rows,pending,_,_=s.restore_rows(r,units,{target['unit_id']:[c]},s.index_for(self.tax,s.base.T1),self.prior['business'],None)
        self.assertFalse(rows);self.assertEqual(pending[0]['unit_id'],target['unit_id'])

    def test_scan_errors_never_report_complete(self):
        r=self.fixture()
        def failed(result,units,group,runner,n):
            return dict(branch_number=n,dictionary_keys=list(group['index']),unit_ids=[u['unit_id'] for u in units],raw=None,errors=['timeout'],audit=[],calls=[])
        with tempfile.TemporaryDirectory() as tmp,patch.object(s,'scan_branch',failed),patch.object(s,'verify_candidates',return_value=([],[],[],['timeout'])),patch.object(s,'alternatives',return_value=([],[],[],[],['timeout'])):
            out=s.process(r,self.tax,self.prior['business'],None,Path(tmp))
        self.assertFalse(out['label_supplement_coverage']['all_branches_checked'])
        self.assertFalse(out['label_supplement_coverage']['all_candidates_adjudicated'])
        self.assertEqual(len(out['rows']),len(r['rows']))

    def test_markdown_quote_marker_preserves_literal_words(self):
        r=self.fixture();c=self.candidate(r);c['quotes']=['>约162㎡上叠']
        s.normalize_evidence([c],s.audit_units(r),r['document'],[])
        self.assertEqual(c['quotes'],['约162㎡上叠'])

    def test_same_quote_can_prove_object_and_attribute(self):
        r=self.fixture();c=self.candidate(r);c['context_quotes']=[]
        self.assertFalse(s.evidence_errors(c,{u['unit_id']:u for u in s.audit_units(r)},s.index_for(self.tax,s.base.T1),r['document']))

    def test_existing_rejected_found_is_withdrawn_only_after_second_rejection(self):
        r=self.fixture('T1-879334445254348759');uid=r['document']['record_id']+'-M001'
        candidate=dict(unit_id=uid,key='D0384',quotes=['游泳馆'],context_quotes=['体育公园'],
            object='体育公园',reason='公园不是会所',confidence=1,verdict='unsupported')
        def scan(result,units,group,runner,n):
            found=[candidate] if 'D0384' in group['index'] else []
            existing=[dict(candidate,unit_id=u['unit_id'],key=k,verdict='unsupported' if u['unit_id']==uid and k=='D0384' else 'supported') for u in units for k in u['existing_keys'] if k in group['index']]
            return dict(branch_number=n,dictionary_keys=list(group['index']),unit_ids=[u['unit_id'] for u in units],
                raw=dict(found=found,existing_decisions=existing,unresolved_facts=[]),errors=[],audit=[],calls=[])
        def verify(result,units,candidates,index,runner,phase):
            return [dict(c,verdict='unsupported',program_issues=[],replacement_keys=[]) for c in candidates],[],[],[]
        with tempfile.TemporaryDirectory() as tmp,patch.object(s,'scan_branch',scan),patch.object(s,'verify_candidates',verify),patch.object(s,'alternatives',return_value=([],[],[],[],[])):
            out=s.process(r,self.tax,self.prior['business'],None,Path(tmp))
        self.assertEqual(out['label_supplement_coverage']['withdrawn_wrong_tags'],1)
        self.assertNotIn(uid,{u['unit_id'] for u in out['rows']})
        self.assertIn(uid,{u['unit_id'] for u in out['pending_units']})

    def test_catalog_quotes_are_literal_and_cannot_cross_unit(self):
        r=self.fixture();units=s.audit_units(r);catalog=s.evidence_catalog(units)
        for e in catalog:self.assertEqual(r['document']['text'][e['start']:e['end']],e['text'])
        c=self.candidate(r);c.update(attribute_keys=[catalog[0]['source_key']],context_keys=[])
        s.bind_evidence([c],catalog)
        self.assertIn('属性证据编号属于其他单元',c['_evidence_issues'])

    def test_area_cue_is_nomination_not_auto_tag(self):
        r=self.fixture();cues=s.area_review_cues(s.audit_units(r),s.index_for(self.tax,s.base.T1))
        cue=next(c for c in cues if c['unit_id'].endswith('M008'))
        self.assertEqual(cue['confidence'],0);self.assertTrue(cue['proposal_issues'])

    def test_known_scope_errors_are_uncertainty_triggers(self):
        idx=s.index_for(self.tax,s.base.T1)
        for key,quote in [('D0201','横向宽厅达到约8.5米'),('D0415','宋风意境中庭'),('D0192','LDK全景通透公区'),('D0403','带建用地面积约3.34万方体育公园'),('D0186','實用面積4,732呎')]:
            self.assertTrue(s.object_scope_risks(dict(key=key,quotes=[quote],context_quotes=[]),idx))
        for key,quote in [('D0201','餐厅十二米面宽'),('D0415','宋风外立面'),('D0192','南北通透'),('D0186','建筑面积约180㎡')]:
            self.assertFalse(s.object_scope_risks(dict(key=key,quotes=[quote],context_quotes=[]),idx))

    def test_supported_blank_object_is_still_not_accepted(self):
        r=self.fixture();units=s.audit_units(r);catalog=s.evidence_catalog(units);c=self.candidate(r);c['candidate_id']='C1'
        evidence=next(e for e in catalog if e['unit_id']==c['unit_id'])
        raw=dict(candidate_id='C1',attribute_keys=[evidence['source_key']],context_keys=[],object='',reason='需核',confidence=1,
            verdict='supported',same_object=True,property_matches=True,modality_preserved=True,replacement_keys=[],
            history_condition_resolved=True,history_resolution='')
        with patch.object(s,'review',return_value=({'decisions':[raw]},[],[],[])):
            decisions,_,_,_=s.verify_candidates(r,units,[c],s.index_for(self.tax,s.base.T1),None,'test')
        self.assertEqual(decisions[0]['unit_id'],c['unit_id']);self.assertEqual(decisions[0]['key'],c['key'])
        self.assertIn('缺少对象或匹配理由',decisions[0]['program_issues'])

    def test_repeated_quote_keeps_selected_occurrence(self):
        text='主卧。面积18㎡。次卧。面积18㎡。'
        catalog=s.evidence_catalog([dict(unit_id='U1',start=0,end=len(text),text=text)])
        occurrences=[e for e in catalog if e['text']=='面积18㎡。']
        item=dict(unit_id='U1',key='D0217',attribute_keys=[occurrences[-1]['source_key']],context_keys=[])
        s.bind_evidence([item],catalog)
        self.assertEqual(item['attribute_spans'][0]['start'],text.rfind('面积18㎡。'))
        self.assertNotEqual(item['attribute_spans'][0]['start'],text.find('面积18㎡。'))

    def test_definition_risk_is_a_review_request_not_automatic_deletion(self):
        idx=s.index_for(self.tax,s.base.T2)
        self.assertTrue(s.supplement_definition_risks(dict(key='D0065'),idx))
        self.assertTrue(s.supplement_definition_risks(dict(key='D0166'),idx))
        self.assertTrue(s.supplement_definition_risks(dict(key='D0414'),idx))
        self.assertFalse(s.supplement_definition_risks(dict(key='D0142'),idx))

    def test_failed_new_risk_review_does_not_delete_baseline_label(self):
        r=self.fixture();c=self.candidate(r);idx=s.index_for(self.tax,s.base.T1)
        with patch.object(s,'verify_candidates',return_value=([],[],[],['timeout'])):
            kept,events,_,_,errors,_=s.gate_new_supplements(r,s.audit_units(r),{c['unit_id']:[c]},idx,None,set())
            self.assertFalse(kept[c['unit_id']]);self.assertTrue(events);self.assertEqual(errors,['timeout'])
            kept,events,_,_,errors,_=s.gate_new_supplements(r,s.audit_units(r),{c['unit_id']:[c]},idx,None,{(c['unit_id'],c['key'])})
            self.assertEqual(kept[c['unit_id']],[c]);self.assertFalse(events);self.assertFalse(errors)

    def test_general_risk_and_historic_rejection_are_separate(self):
        r=self.fixture();c=self.candidate(r);idx=s.index_for(self.tax,s.base.T1)
        def verify(result,units,candidates,*args):
            self.assertTrue(candidates[0]['definition_risks'])
            self.assertEqual(candidates[0]['history_conflicts'],s.historic_rejections(r,c['unit_id'],c['key']))
            return [],[],[],['timeout']
        with patch.object(s,'verify_candidates',verify):s.gate_new_supplements(r,s.audit_units(r),{c['unit_id']:[c]},idx,None,set())

    def test_main_bedroom_presence_does_not_default_to_count_one(self):
        idx=s.index_for(self.tax,s.base.T1)
        self.assertTrue(s.object_scope_risks(dict(key='D0210',quotes=['主卧打造25㎡套房'],context_quotes=[]),idx))
        self.assertFalse(s.object_scope_risks(dict(key='D0210',quotes=['有两间主卧'],context_quotes=[]),idx))


if __name__=='__main__':unittest.main()
