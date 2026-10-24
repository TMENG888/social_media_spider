"""No API calls: verify request isolation, bounded context, and stable evidence."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import full_dictionary_supplement_v92 as s
from full_dictionary_supplement_v93 import ScopedApiRunner
from token_cost_report_v93 import report as cost_report
from package_two_workbooks_v87 import pending_fact_display,supplement_costs
import project_context_v90 as project_context


class SingleUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prior=json.loads(s.DEFAULT_PRIOR.read_text(encoding='utf-8'))
        cls.tax=s.base.load_taxonomy(s.DEFAULT_TAXONOMY)

    def fixture(self):
        r=copy.deepcopy(next(r for r in self.prior['results'] if r['document']['record_id']=='T1-2651643050694719236'))
        r['label_request_mode']='single_unit';return r

    def test_scan_is_one_slice_not_full_article(self):
        r=self.fixture();unit=s.audit_units(r)[-1];idx=s.index_for(self.tax,s.base.T1);group=s.partitions.groups(idx)[0]
        def reply(system,payload,schema,*args):
            self.assertEqual(payload['audit_units'],[unit]);self.assertEqual(payload['source_text'],unit['text'])
            self.assertNotEqual(payload['source_text'],r['document']['text']);self.assertEqual(payload['request_scope'],'single_unit')
            self.assertLessEqual(sum(len(e['text']) for e in payload['identity_context']),1200)
            return dict(checked_keys=list(group['index']),found=[],existing_decisions=[],unresolved_facts=[]),[],[],[]
        with patch.object(s,'review',reply):s.scan_branch(r,[unit],group,None,0)

    def test_scoped_catalog_retains_global_evidence_ids(self):
        r=self.fixture();full={e['source_key']:e for e in s.evidence_catalog(s.audit_units(r))}
        for unit in s.audit_units(r):
            payload,catalog=s.scoped_request(r,[unit])
            for entry in catalog:self.assertEqual(entry,full[entry['source_key']])
            self.assertTrue(any(e['unit_id']==unit['unit_id'] for e in catalog))
            self.assertLessEqual(len(payload['identity_context']),8)

    def test_context_cannot_supply_attribute_evidence(self):
        r=self.fixture();unit=s.audit_units(r)[-1];payload,catalog=s.scoped_request(r,[unit])
        other=next(e for e in catalog if e['unit_id']!=unit['unit_id'])
        item=dict(unit_id=unit['unit_id'],key='D0186',attribute_keys=[other['source_key']],context_keys=[])
        s.bind_evidence([item],catalog);self.assertIn('属性证据编号属于其他单元',item['_evidence_issues'])

    def test_mixed_scope_payload_is_rejected(self):
        r=self.fixture()
        with self.assertRaises(ValueError):s.scoped_request(r,s.audit_units(r)[:2])

    def test_verification_is_batched_only_within_same_unit(self):
        r=self.fixture();units=s.audit_units(r);seen=[]
        candidates=[dict(unit_id=u['unit_id'],key='D0168',candidate_id=str(i),quotes=[],context_quotes=[]) for i,u in enumerate(units[:2])]
        def reply(system,payload,*args):
            self.assertEqual(len(payload['target_units']),1);uid=payload['target_unit_id'];seen.append(uid)
            self.assertTrue(all(c['unit_id']==uid for c in payload['candidates']))
            self.assertEqual(payload['source_text'],payload['target_units'][0]['text'])
            return {'decisions':[dict(candidate_id=c['candidate_id'],attribute_keys=[],context_keys=[],object='',reason='不支持',confidence=1,
                verdict='unsupported',same_object=False,property_matches=False,modality_preserved=True,replacement_keys=[],
                history_condition_resolved=False,history_resolution='',risk_conditions_satisfied=False,risk_resolution='') for c in payload['candidates']]},[],[],[]
        with patch.object(s,'review',reply):decisions,*_=s.verify_candidates(r,units,candidates,s.index_for(self.tax,s.base.T1),None,'test')
        self.assertEqual(len(seen),2);self.assertEqual(len(decisions),2)

    def test_alternatives_is_one_unit_per_request(self):
        r=self.fixture();units=s.audit_units(r)[:2];seen=[]
        def reply(system,payload,*args):
            self.assertEqual(len(payload['audit_units']),1);seen.append(payload['target_unit_id'])
            return {'found':[],'unresolved_facts':[]},[],[],[]
        with patch.object(s,'review',reply):s.alternatives(r,units,[],[],s.index_for(self.tax,s.base.T1),None)
        self.assertEqual(seen,[u['unit_id'] for u in units])

    def test_scan_task_count_is_units_times_all_groups(self):
        r=self.fixture();seen=[]
        def scan(result,units,group,runner,n):
            self.assertEqual(len(units),1);seen.append((units[0]['unit_id'],n))
            return dict(branch_number=n,dictionary_keys=list(group['index']),unit_ids=[units[0]['unit_id']],
                raw=dict(found=[],existing_decisions=[],unresolved_facts=[]),errors=[],audit=[],calls=[])
        with tempfile.TemporaryDirectory() as d,patch.object(s,'scan_branch',scan),patch.object(s,'verify_candidates',return_value=([],[],[],[])),patch.object(s,'alternatives',return_value=([],[],[],[],[])):
            out=s.process(r,self.tax,self.prior['business'],None,Path(d),request_mode='single_unit')
        count=len(s.audit_units(r))*len(s.partitions.groups(s.index_for(self.tax,s.base.T1)))
        self.assertEqual(len(seen),count);self.assertEqual(len(set(seen)),count)
        self.assertEqual(out['label_supplement_coverage']['max_target_units_per_request'],1)

    def test_complete_comment_stays_single_target(self):
        r=copy.deepcopy(next(r for r in self.prior['results'] if r['document']['kind']=='评论'));r['label_request_mode']='single_unit'
        units=s.audit_units(r);payload,_=s.scoped_request(r,units)
        self.assertEqual(len(units),1);self.assertEqual(payload['source_text'],r['document']['text'])
        self.assertLessEqual(len(payload['parent_identity_context']),400)

    def test_previous_semantic_rejection_is_preserved(self):
        r=self.fixture();r['label_supplement_events']=[dict(unit_id='U1',key='D0384',verdict='unsupported',confidence=.99,原因='公共公园不是会所')]
        self.assertIn('公共公园不是会所',s.historic_rejections(r,'U1','D0384'))

    def test_runtime_blocks_mixed_request_before_network(self):
        r=self.fixture();units=s.audit_units(r)[:2];scope,_=s.scoped_request(r,[units[0]])
        with tempfile.TemporaryDirectory() as d:
            runner=ScopedApiRunner(Path(d),10,key='offline-placeholder-never-sent')
            with patch.object(s.ApiRunner,'call') as network,self.assertRaises(AssertionError):
                runner.call('',dict(scope,audit_units=units),r['document'],'紧凑test')
            network.assert_not_called()

    def test_cost_counts_saved_failed_and_current_attempts(self):
        metric=dict(topic='专题',source_type='文章',status='success',attempts=[{'usage':{'prompt_tokens':1000,
            'completion_tokens':100,'prompt_tokens_details':{'cached_tokens':200}}}])
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d);s.save_json(directory/'calls'/'success.json',{'metrics':metric})
            s.save_json(directory/'call_attempt_history'/'failure.json',{'metrics':dict(metric,status='failed',attempts=[{'http_status':500}])})
            value=cost_report(directory)['total']
        self.assertEqual(value['request_records'],2);self.assertEqual(value['http_or_network_attempts'],2)
        self.assertEqual(value['attempts_without_usage'],1);self.assertEqual(value['prompt_tokens'],1000)
        self.assertEqual(value['uncached_input_tokens'],800);self.assertEqual(value['total_known_tokens'],1100)
        self.assertAlmostEqual(value['known_estimated_yuan'],.000248)

    def test_missing_token_prices_are_not_zero_cost_claims(self):
        metric=dict(topic='专题',source_type='评论',status='failed',attempts=[{'usage':{'prompt_tokens':40000,'completion_tokens':100}}])
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d);s.save_json(directory/'calls'/'large.json',{'metrics':metric})
            value=cost_report(directory)['total']
        self.assertEqual(value['usage_records_without_applicable_price'],1);self.assertEqual(value['total_known_tokens'],40100)

    def test_pending_display_resolves_only_literal_target_evidence(self):
        r=self.fixture();unit=s.audit_units(r)[0];entry=next(e for e in s.evidence_catalog(s.audit_units(r)) if e['unit_id']==unit['unit_id'])
        fact=dict(unit_id=unit['unit_id'],quotes=[entry['source_key'],'Invented translation'],fact='待核',reason='模型意见')
        display=pending_fact_display(fact,r)
        self.assertEqual(display['原文证据'],[entry['text']]);self.assertIn('未逐字定位',display['待核原因'])

    def test_pending_display_omits_long_model_process_text(self):
        r=self.fixture();unit=s.audit_units(r)[0]
        fact=dict(unit_id=unit['unit_id'],quotes=[],fact='待核',reason='不稳定原始模型过程'*40)
        display=pending_fact_display(fact,r)
        self.assertLess(len(display['待核原因']),120);self.assertNotIn(fact['reason'],display['待核原因'])

    def test_workbook_cost_table_counts_every_attempt(self):
        metric=dict(topic='专题',source_type='评论',phase='测试',status='success',attempts=[
            {'usage':{'prompt_tokens':20,'completion_tokens':2,'prompt_tokens_details':{'cached_tokens':8}}},
            {'usage':{'prompt_tokens':10,'completion_tokens':4,'prompt_tokens_details':{'cached_tokens':2}}},
            {'network_error':'Timeout'}])
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d);s.save_json(directory/'calls'/'request.json',{'metrics':metric})
            row=supplement_costs(directory)['专题'][0];total=cost_report(directory)['total']
        self.assertEqual(row['HTTP尝试数'],3)
        self.assertEqual(row['已知输入Token'],30)
        self.assertEqual(row['已知缓存Token'],10)
        self.assertEqual(row['已知输出Token'],6)
        self.assertEqual(row['未知usage的HTTP尝试数'],1)
        self.assertEqual(row['已知输入Token'],total['prompt_tokens'])
        self.assertEqual(row['已知估算费用元'],total['known_estimated_yuan'])

    def test_recovered_project_identity_also_uses_single_target(self):
        r=copy.deepcopy(next(r for r in self.prior['results'] if r['document']['record_id']=='T2-1263114957749348749'))
        r['label_request_mode']='single_unit';r['rows']=r['rows'][:2]
        for row in r['rows']:row.update(project_id=[],项目名称=[],项目角色=[])
        seen=[]
        def reply(system,payload,schema,doc,phase,runner):
            self.assertEqual(len(payload['requested_units']),1);unit=payload['requested_units'][0]
            self.assertEqual(payload['source_text'],unit['text']);self.assertEqual(payload['source'],unit['text'])
            self.assertNotEqual(payload['source'],doc['text']);self.assertEqual(payload['request_scope'],'single_unit')
            self.assertEqual(phase,'紧凑单片项目身份补全-v93');seen.append(unit['unit_id'])
            return {'units':[dict(unit_id=unit['unit_id'],decision='uncertain',bindings=[],other_name='',why='证据不足',confidence=.95)]},[],[],[]
        with patch.object(project_context,'review',reply):project_context.process(r,self.prior['business'],None)
        self.assertEqual(len(seen),2)


if __name__=='__main__':unittest.main()
