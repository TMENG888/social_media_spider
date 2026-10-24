import unittest
from unittest.mock import Mock
import slice_precision_v9 as p
import test_local_retag_api_v9 as local
import audit_local_coverage_v9 as coverage


class PartitionContract(unittest.TestCase):
    def group(self,start):
        return {'source_start_id':start,'object':'户型','theme':'厨房配置','why':'独立完整事实','confidence':.95}

    def test_complete_coverage_ends_are_program_filled(self):
        issues,groups=p.validate_partition({'groups':[self.group(4),self.group(8)]},4,12)
        self.assertEqual([],issues)
        self.assertEqual([(4,7),(8,12)],[(g['source_start_id'],g['source_end_id']) for g in groups])

    def test_missing_beginning_rejected(self):
        self.assertTrue(p.validate_partition({'groups':[self.group(5)]},4,12)[0])

    def test_unsorted_duplicate_out_of_range_rejected(self):
        for starts in ([4,8,7],[4,4],[4,13]):
            self.assertTrue(p.validate_partition({'groups':[self.group(s) for s in starts]},4,12)[0])

    def test_comment_never_calls_model_or_splits(self):
        runner=Mock()
        result=p.probe_record({'document':{'kind':'评论','record_id':'C1','text':'长评论'*1000}},runner,600)
        self.assertTrue(result['comment_unchanged'])
        runner.call.assert_not_called()

    def test_long_single_object_may_remain_one_piece(self):
        issues,groups=p.validate_partition({'groups':[self.group(4)],'keep_long_reason':'一个完整配置事实'},4,12)
        self.assertEqual([],issues)
        self.assertEqual(1,len(groups))

    def test_local_judgment_does_not_transmit_full_article_or_title(self):
        doc={'kind':'文章','topic':p.p.base.T1,'text':'不相关的全文事实','title':'标题幻觉','parent':{'文章内容':'父文章设施'}}
        payload=local.local_payload(doc,{'excerpt':'当前切片'},[],'必要对象背景')
        self.assertEqual('当前切片',payload['slice_text'])
        self.assertNotIn('不相关的全文事实',str(payload))
        self.assertNotIn('标题幻觉',str(payload))
        self.assertNotIn('父文章设施',str(payload))

    def test_research_scope_is_not_a_project_identity(self):
        doc={'kind':'文章','topic':'北京臻澐项目口碑'}
        self.assertNotIn('北京臻澐',str(local.local_payload(doc,{'excerpt':'海晏'},[],'')))

    def test_supported_status_with_unsupported_reason_is_quarantined(self):
        runner=Mock()
        runner.call.return_value=({'decisions':[{'choice_key':'D0380','status':'supported',
            'direct_quote':'茶室','why':'定义限定会所；因此不支持，标记为unsupported','confidence':.95}]},
            {'status':'success'})
        case={'case_id':'S1','document':{},'child':{'excerpt':'私人茶室'},'context':''}
        result=coverage.audit((case,1,[('D0380',{'emphasis':'会所茶室','instruction':'记录会所茶室'})]),runner)
        self.assertEqual([],result['supported'])
        self.assertTrue(result['issues'])


if __name__=='__main__':unittest.main()
