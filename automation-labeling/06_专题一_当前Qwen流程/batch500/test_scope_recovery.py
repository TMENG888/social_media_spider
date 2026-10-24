import copy,unittest
from types import SimpleNamespace
from unittest.mock import Mock
import recovery_scope_guard

class ScopeTests(unittest.TestCase):
    def run_scope(self,owned,quote='独立商业中心',deliver=False):
        unit={'index':1,'start':0,'end':6,'text':'独立商业中心','deliver':deliver,'reason':'范围待核','labels':[{'tag_id':'example'}]}
        audit={'table_audit':['unchanged full dictionary audit']}
        original=Mock(return_value=({'prior':True},audit))
        batch=SimpleNamespace(pipeline=SimpleNamespace(label_units_exhaustive=original,obj=lambda v:v,arr=lambda v:v),save=Mock(),ROOT=__import__('pathlib').Path('E:/Codex/work/offline'))
        runner=SimpleNamespace(call=Mock(return_value=({'residential_owned':owned,'reason':'独立核实对象','evidence_quotes':[quote] if quote else []},{'status':'success'})))
        recovery_scope_guard.install(batch)
        result=batch.pipeline.label_units_exhaustive({'record_id':'test','title':'title','text':'独立商业中心'},[unit],[],runner)
        return unit,result,runner
    def test_nonresidential_veto_preserves_audit(self):
        u,r,_=self.run_scope(False)
        self.assertEqual(u['labels'],[])
        self.assertEqual(r[1]['table_audit'],['unchanged full dictionary audit'])
        self.assertEqual(u['scope_conflict_adjudication']['original_labels'],[{'tag_id':'example'}])
    def test_residential_keeps_labels(self):
        u,_,_=self.run_scope(True)
        self.assertEqual(u['labels'],[{'tag_id':'example'}])
    def test_no_conflict_does_not_call_model(self):
        u,_,runner=self.run_scope(True,deliver=True)
        runner.call.assert_not_called()
    def test_invented_quote_is_rejected(self):
        with self.assertRaises(AssertionError):self.run_scope(True,'捏造证据')
    def test_residential_without_evidence_is_rejected(self):
        with self.assertRaises(AssertionError):self.run_scope(True,'')
if __name__=='__main__':unittest.main()
