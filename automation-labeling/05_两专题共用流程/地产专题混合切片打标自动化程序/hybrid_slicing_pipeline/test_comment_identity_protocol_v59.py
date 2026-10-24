import copy
import unittest
import comment_identity_protocol_v59 as v

class IdentityProtocolTests(unittest.TestCase):
    def setUp(self):
        self.comment='【父评论｜路人】750米，你飞过去啊【子评论1｜某房产机构】项目规划架桥。'
        self.parent='甲苑在海淀。距离地铁站仅750米。乙苑距离地铁两公里。'
        self.projects=[{'name':'甲苑','aliases':['甲'],'id':'C1','role':'核心竞品'}]
        cc,pc=v.catalogs(self.comment,self.parent)
        self.target={'name':'甲苑','mode':'parent_relation','comment_keys':[cc[0]['source_key']],
            'parent_identity_keys':[pc[0]['source_key']],
            'parent_relation_keys':[e['source_key'] for e in pc if '750米' in e['text']],
            'supported':True,'why':'主评论距离与甲苑父文距离唯一对应','confidence':.95}
        self.response={'targets':[self.target],'ambiguous_reason':None}

    def test_separate_identity_and_relation(self):
        targets,errors=v.verify(self.comment,self.parent,self.response,self.projects)
        self.assertFalse(errors);self.assertEqual(targets[0]['id'],'C1')
        self.assertIn('750米',targets[0]['evidence']['parent_relation_quote'])

    def test_missing_identity_not_single_candidate_inheritance(self):
        self.target['parent_identity_keys']=self.target['parent_relation_keys']
        self.assertFalse(v.verify(self.comment,self.parent,self.response,self.projects)[0])

    def test_cross_namespace_rejected(self):
        self.target['comment_keys']=self.target['parent_relation_keys']
        self.assertFalse(v.verify(self.comment,self.parent,self.response,self.projects)[0])

    def test_valid_rejection_not_approval(self):
        self.target['supported']=False
        self.assertFalse(v.verify(self.comment,self.parent,self.response,self.projects)[0])

    def test_low_confidence_not_defaulted(self):
        self.target['confidence']=.89
        self.assertFalse(v.verify(self.comment,self.parent,self.response,self.projects)[0])

    def test_duplicate_targets_not_overwritten(self):
        self.response['targets'].append(copy.deepcopy(self.target))
        self.assertFalse(v.verify(self.comment,self.parent,self.response,self.projects)[0])

    def test_primary_role_payload_excludes_child(self):
        payload=v.role_payload(self.comment)
        self.assertNotIn('房产机构',str(payload))
        self.assertIn('路人',str(payload))

    def test_reply_evidence_cannot_prove_primary_role(self):
        cc=v.source_catalog(self.comment)
        response={'role':'自媒体及行业账号','known':True,'evidence_keys':[cc[-1]['source_key']],
                  'why':'子回复是机构','confidence':.99}
        self.assertEqual(v.verify_role(self.comment,response)[0],'不明')

if __name__=='__main__':unittest.main()
