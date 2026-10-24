import copy
import unittest
from unittest.mock import Mock
import delivery_v5 as v
from test_delivery_v4 import fixture, TAG, BUS

class Contracts(unittest.TestCase):
    def test_complete_catalogue(self):
        tags=v.base.load_taxonomy(v.TAXONOMY)
        for topic,n in [(v.base.T1,323),(v.base.T2,580)]:
            rows=v.catalogue(tags,topic)
            self.assertEqual(len(rows),n)
            self.assertTrue(all(set(r)=={'标签强调方向','打标说明'} for r in rows))

    def test_ambiguous_direction_rejected(self):
        with self.assertRaises(ValueError):v.direction_index([TAG,dict(TAG,tag_id='other')],v.base.T2)

    def test_full_source_and_exact_mapping(self):
        doc,u,_=fixture()
        payload=v.request_payload(doc,[TAG],BUS)
        self.assertEqual(''.join(s['text'] for s in payload['source_segments']),doc['text'])
        raw={'units':[dict(u,source_start_id=1,source_end_id=1,labels=[{'direction':'中央空调','evidence_start_id':1,'evidence_end_id':1}])]}
        mapped=v.map_units(raw,payload['source_segments'],[TAG],v.base.T2)
        self.assertEqual(mapped['units'][0]['labels'][0]['tag_id'],TAG['tag_id'])
        raw['units'][0]['labels'][0]['direction']='空调改写词'
        self.assertFalse(v.map_units(raw,payload['source_segments'],[TAG],v.base.T2)['units'][0]['labels'])

    def test_single_call_failure_no_repair(self):
        doc,_,_=fixture();runner=Mock()
        runner.call.return_value=({}, {'status':'success'})
        result=v.process_document(doc,[TAG],BUS,runner)
        self.assertFalse(result['complete']);self.assertEqual(runner.call.call_count,1)

    def test_comment_no_split(self):
        doc,u,_=fixture('评论');runner=Mock()
        runner.call.return_value=({'units':[u,u]}, {'status':'success'})
        self.assertFalse(v.process_document(doc,[TAG],BUS,runner)['complete'])
        self.assertEqual(runner.call.call_count,1)

    def test_hard_false_positive_guards(self):
        guard=v.guard_for({'labels':[]})
        self.assertEqual(guard('超高得房率的下叠院墅',dict(TAG,emphasis='超高'))[0],'rejected')
        self.assertEqual(guard('挨着高速会不会吵',dict(TAG,l4='高速入口'))[0],'rejected')

    def test_project_inherited_only_from_unique_context(self):
        doc,u,_=fixture('评论');u.update(project_ids=[],project_evidence=[])
        v.fill_project_context(doc,u,BUS)
        self.assertEqual(u['project_ids'],['P01'])

    def test_platform_id_mapping_and_hallucination_clear(self):
        doc,_,_=fixture('评论');doc['row']['文章id']='platform-1'
        doc['text']='【父评论｜某用户】想去'
        row={'project_id':[],'备注':'','观点摘要':'认为园林设计具有文化感和艺术价值','验收状态':'自动通过'}
        trace={};v.apply_comment_mapping(doc,row,trace,BUS)
        self.assertEqual(row['映射文章id'],'platform-1')
        self.assertEqual(row['观点摘要'],'')
        self.assertEqual(row['验收状态'],'需人工审核')

if __name__=='__main__':unittest.main()
