import unittest
import delivery_v11 as pipeline


class FeedbackRunner:
    def __init__(self):self.requests=[];self.focused_count=0

    def call(self,system,payload,doc,phase):
        self.requests.append((phase,payload))
        metrics={'status':'success'}
        if phase.startswith('失败评论摘要不透明'):
            entry=payload['source_evidence_catalog'][0]
            return {'claims':[{'actor_quote':'甲','object_quote':'巴士','claim':'甲未乘坐过，只表达相对选择倾向。',
                              'evidence_keys':[entry['source_key']],'confidence':.95}]},metrics
        if phase.startswith('独立文案证据失败'):
            return {'summary':'甲对巴士乘坐体验很满意。','supported':True,'confidence':.95},metrics
        if phase.startswith('核心证据约束下') or phase.startswith('评论摘要反向失败反馈'):
            self.focused_count+=1
            text='甲对巴士乘坐体验很满意。' if self.focused_count==1 else '甲表示未乘坐过，只倾向在两种方式中选巴士。'
            return {'summary':text,'supported':True,'confidence':.95},metrics
        if 'prose_catalog' in payload:
            key=payload['source_evidence_catalog'][0]['source_key']
            key_protocol='禁止另造assertion_quote' in system or '禁止返回attribute_quote或assertion_quote' in system
            rejecting=key_protocol and '满意' in payload['prose_catalog'][0]['text']
            response={'checks':[{'prose_key':p['prose_key'],'status':'unsupported' if rejecting else 'supported',
                'source_keys':[key],'assertion_quote':p['text'],
                'why':'相对选择未实测不能改为满意' if rejecting else '保留未实测相对偏好',
                'confidence':.95,'object_binding_supported':True,'relation_supported':True,
                'modality_preserved':not rejecting,'qualifiers_preserved':True,
                'object_bindings':[{'assertion_quote':p['text'],'object_quote':None,
                    'object_source_key':None,'attribute_source_key':key,
                    'attribute_quote':payload['source_evidence_catalog'][0]['text'],
                    'generic_or_unresolved':True}]}
                for p in payload['prose_catalog']],
                'coverage':{'captures_primary_points':True,'source_keys':[key],'why':'主要相对选择观点','confidence':.95}}
            if '禁止另造assertion_quote' in system:
                check=response['checks'][0];check.pop('assertion_quote')
                response['object_bindings']=check.pop('object_bindings')
                for binding in response['object_bindings']:
                    binding.pop('assertion_quote');binding['prose_key']=check['prose_key']
            if '禁止返回attribute_quote或assertion_quote' in system:
                check=response['checks'][0];check.pop('assertion_quote')
                response['object_bindings']=check.pop('object_bindings')
                for binding in response['object_bindings']:
                    binding.pop('assertion_quote');binding.pop('attribute_quote')
                    binding.pop('generic_or_unresolved')
                    binding['prose_key']=check['prose_key']
            return response,metrics
        raise AssertionError(phase)


class FeedbackIntegration(unittest.TestCase):
    def test_coverage_true_cannot_bypass_failed_fragment_factual_review(self):
        class FailingFragments(FeedbackRunner):
            def call(self,system,payload,doc,phase):
                result,metrics=super().call(system,payload,doc,phase)
                if '禁止另造assertion_quote' in system or '禁止返回attribute_quote或assertion_quote' in system:
                    for check in result.get('checks',[]):
                        check.update(status='unsupported',relation_supported=False,
                                     why='独立片段事实不受原文支持')
                return result,metrics
        source='【父评论｜甲】我没有坐过巴士，如果巴士和轮渡二选一，也许巴士稍好一点。'
        runner=FailingFragments()
        out,audit,calls,issues=pipeline.independent_prose_review(
            {'topic':'北京臻澐项目口碑','kind':'评论'},
            {'summary':'甲对巴士乘坐体验很满意。','labels':[]},source,'',runner)
        self.assertIsNone(out['summary']);self.assertTrue(issues)

    def test_failed_selector_does_not_discard_usable_complete_source(self):
        class BrokenSelector(FeedbackRunner):
            def call(self,system,payload,doc,phase):
                if phase.startswith(('失败评论摘要不透明','评论核心证据键有界协议恢复')):
                    self.requests.append((phase,payload))
                    return {'claims':[]},{'status':'success'}
                return super().call(system,payload,doc,phase)
        source='【父评论｜甲】我没有坐过巴士，如果巴士和轮渡二选一，也许巴士稍好一点。'
        runner=BrokenSelector()
        out,audit,calls,issues=pipeline.independent_prose_review(
            {'topic':'北京臻澐项目口碑','kind':'评论'},
            {'summary':'甲对巴士乘坐体验很满意。','labels':[]},source,'',runner)
        self.assertFalse(issues);self.assertIn('未乘坐过',out['summary'])
        generations=[p for phase,p in runner.requests if phase.startswith('核心证据约束下')]
        self.assertTrue(generations[0]['selection_unavailable'])
        self.assertEqual([],generations[0]['core_claims']);self.assertEqual(source,generations[0]['source_text'])

    def test_critic_rejection_is_fed_to_bounded_regeneration(self):
        source='【父评论｜甲】我没有坐过巴士，如果巴士和轮渡二选一，也许巴士稍好一点。'
        runner=FeedbackRunner()
        out,audit,calls,issues=pipeline.independent_prose_review(
            {'topic':'北京臻澐项目口碑','kind':'评论'},
            {'summary':'甲对巴士乘坐体验很满意。','labels':[]},source,'',runner)
        self.assertFalse(issues)
        self.assertIn('未乘坐过',out['summary'])
        self.assertNotIn('满意',out['summary'])
        second=[payload for phase,payload in runner.requests if phase.startswith('评论摘要反向失败反馈')]
        self.assertEqual(1,len(second))
        self.assertTrue(any(c.get('accepted') is False for c in second[0]['independent_prose_issues']))
        self.assertEqual(2,runner.focused_count)
        self.assertFalse(audit[0]['passed'])
        self.assertTrue(audit[-1]['passed'])


if __name__=='__main__':unittest.main()
