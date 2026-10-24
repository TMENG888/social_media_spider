import copy, json, sys, unittest
sys.dont_write_bytecode=True
import project_priority as q
from run_pilot import PILOT

class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory=q.p.read(q.BASE);cls.by={x['record_id']:x for x in cls.inventory['sources']}
    def test_exact_base_inventory(self):
        self.assertEqual(q.sha(q.BASE),'b962dbf254cd52f982158683134529d3b585e8c09df9365864a755f354e4f3d1')
        self.assertEqual(self.inventory['source_counts'],{'文章':111,'评论':476})
    def test_pilot_ten_unique_existing_comments(self):
        self.assertEqual(len(PILOT),10);self.assertEqual(len({r for r,_ in PILOT}),10)
        for rid,_ in PILOT:self.assertEqual(self.by[rid]['kind'],'评论')
    def test_stage_a_whitelist_no_inherited_label_object(self):
        for rid,_ in PILOT:
            s=self.by[rid];payload=q.own_payload(s)
            self.assertEqual(set(payload),{'comment_text','known_projects','facts'})
            for fact in payload['facts']:self.assertEqual(set(fact),{'fact_id','tag_id','evidence','tag_name','tag_definition'})
            changed=copy.deepcopy(s);changed['document']['parent']={'文章标题':'LEAK_PARENT'}
            for outcome in changed['outcomes'].values():
                for view in outcome['views']:
                    view['project_id']='LEAK_OLD'
                    for label in view['labels']:label['reason']='LEAK_REASON';label['object']='LEAK_OBJECT'
            self.assertNotIn('LEAK_',json.dumps(q.own_payload(changed)))
    def test_every_old_label_accounted(self):
        for rid,_ in PILOT:
            s=self.by[rid];fs=q.facts(s)
            self.assertEqual(sum(len(f['refs']) for f in fs),sum(len(v['labels']) for o in s['outcomes'].values() for v in o['views']))
    def test_quote_must_be_literal(self):
        x={'id':'P01','name':'北京臻澐','quote':'不存在'}
        self.assertIn('nonliteral_project_quote',q.validate_projects([x],{'comment_text':'臻澐'}))
    def test_nickname_not_evidence(self):
        self.assertEqual(q.comment_body('【子评论1｜保利熙瑞-李】好看'),'好看')
    def test_brand_only_needs_context(self):
        b=[{'fact_id':'F001','decision':'explicit','projects':[{'id':'C01','name':'建发海晏','quote':'建发一定买现房看'}]}]
        events=q.brand_guard(b,'建发一定买现房看。各种减配')
        self.assertEqual(len(events),1);self.assertEqual(b[0]['decision'],'unresolved')
    def test_named_alias_not_blocked(self):
        b=[{'fact_id':'F001','decision':'explicit','projects':[{'id':'C01','name':'建发海晏','quote':'建发海晏'}]}]
        self.assertEqual(q.brand_guard(b,'建发海晏'),[])
    def test_no_forced_four_project(self):
        s=self.by[PILOT[0][0]];fs=q.facts(s)
        overlay={'source_digest':q.digest(s),'facts':fs,'formal_stage_proofs':[],
            'bindings':[{'fact_id':f['fact_id'],'decision':'explicit','method':'comment_explicit','reason':'说别盘',
            'projects':[{'id':'OTHER','name':'其他楼盘','quote':'别盘','evidence_field':'comment_text'}]} for f in fs]}
        before=q.digest(s);revised=q.apply_overlay(s,overlay)
        self.assertEqual(q.digest(s),before)
        self.assertEqual(revised['state'],'excluded_after_project_review')
        self.assertEqual(len(revised['project_attribution_parked_labels']),sum(len(f['refs']) for f in fs))
        self.assertEqual(revised['units'],s['units'])
    def test_unresolved_not_force_inherited(self):
        s=self.by[PILOT[0][0]];fs=q.facts(s)
        overlay={'source_digest':q.digest(s),'facts':fs,'formal_stage_proofs':[],
            'bindings':[{'fact_id':f['fact_id'],'decision':'ambiguous','method':'ambiguous','reason':'多盘不清楚','projects':[]} for f in fs]}
        revised=q.apply_overlay(s,overlay)
        self.assertTrue(all(x['reason']=='ambiguous' for x in revised['project_attribution_parked_labels']))

if __name__=='__main__':unittest.main()
