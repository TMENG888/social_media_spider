import unittest
import delivery_v7 as v


class BranchContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.tax=v.v.base.load_taxonomy(v.v.legacy.TAXONOMY)

    def test_all_applicable_tags_exactly_once(self):
        for topic,n in [(v.v.base.T1,323),(v.v.base.T2,580)]:
            chunks=v.branches(self.tax,topic)
            keys=[key for chunk in chunks for key,tag in chunk]
            self.assertEqual(len(keys),n)
            self.assertEqual(len(set(keys)),n)
            self.assertTrue(all(0<len(chunk)<=40 for chunk in chunks))

    def test_reject_self_contradictory_reason(self):
        self.assertTrue(v.contradiction('此处不匹配总车位数量标签，因为没有具体数量。'))
        self.assertTrue(v.contradiction('未明确提及具体的照明通风设施配置，故不匹配。'))
        self.assertFalse(v.contradiction('原文明确车位尺寸5.5×2.5米，支持车位尺度。'))

    def test_complete_branch_partition(self):
        chunk=v.branches(self.tax,v.v.base.T1)[0];index=dict(chunk)
        raw={'matches':[],'unsupported_keys':list(index),'ambiguous':[],'confidence':.95,'issues':[]}
        self.assertEqual([],v.branch_check(raw,index))
        raw['unsupported_keys'].pop()
        self.assertTrue(any('遗漏' in issue for issue in v.branch_check(raw,index)))

    def test_conflict_resolution_requires_one_decision_per_key(self):
        raw={'matches':[],'unsupported_keys':['D0165'],'ambiguous':[{'choice_key':'D0165','reason':'有歧义'}]}
        resolved,issues=v.apply_decisions(raw,{'decisions':[{'choice_key':'D0165','status':'supported','why':'明确总图容积率1.05','evidence_start_id':1,'evidence_end_id':1}]},{'D0165'})
        self.assertEqual([],issues)
        self.assertEqual([],resolved['unsupported_keys'])
        self.assertEqual([],resolved['ambiguous'])
        self.assertEqual('D0165',resolved['matches'][0]['choice_key'])
        _,issues=v.apply_decisions(raw,{'decisions':[]},{'D0165'})
        self.assertTrue(issues)

    def test_disputed_keys_include_conflict_and_missing(self):
        index={'D0165':{},'D0164':{}}
        raw={'matches':[{'choice_key':'D0165','why':'明确容积率'}],'unsupported_keys':['D0165'],'ambiguous':[]}
        self.assertEqual({'D0165','D0164'},v.disputed_keys(raw,index))

    def test_slice_merge_is_not_label_removal_reason(self):
        self.assertTrue(v.invalid_rejection_reason('已作为整体权益被覆盖，无需单独拆分，避免碎片化'))
        self.assertFalse(v.invalid_rejection_reason('只有预留管线，原文未承诺已安装中央空调'))
        self.assertTrue(v.invalid_rejection_reason('因D0062已覆盖其核心意图，且道路标签需要距离数据，故排除'))


if __name__=='__main__':unittest.main()
