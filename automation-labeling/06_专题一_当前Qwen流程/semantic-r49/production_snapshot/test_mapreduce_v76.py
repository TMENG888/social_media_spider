import unittest
import mapreduce_v76 as m

class MapReduceTests(unittest.TestCase):
    def test_exhaustive_partition(self):
        index = {str(i): {'l1': '产品' if i < 90 else '客户', 'l2': str(i % 3), 'l3': None} for i in range(121)}
        groups = m.groups(index, 20)
        keys = [k for g in groups for k in g['index']]
        self.assertEqual(len(keys), 121)
        self.assertEqual(set(keys), set(index))
        self.assertTrue(all(len(g['index']) <= 20 for g in groups))

    def test_literal_route_distinct_objects(self):
        text = '甲户型层高3米。乙户型层高3.2米。'
        entries = m.source_catalog(text)
        proposal = {'choice_key': 'D0195', 'source_keys': [entries[1]['source_key']]}
        segments = [{'id': 1, 'start': 0, 'end': 8, 'text': text[:8]},
                    {'id': 2, 'start': 8, 'end': len(text), 'text': text[8:]}]
        buckets = m.route([proposal], segments)
        self.assertEqual(buckets[0], [])
        self.assertEqual(len(buckets[1]), 1)

    def test_duplicate_proposals_union(self):
        text = '会所设25米恒温泳池。'
        key = m.source_catalog(text)[0]['source_key']
        pp = [{'choice_key': 'D1', 'source_keys': [key]}, {'choice_key': 'D1', 'source_keys': [key]},
              {'choice_key': 'D2', 'source_keys': [key]}]
        buckets = m.route(pp, [{'id': 1, 'start': 0, 'end': len(text), 'text': text}])
        self.assertEqual(len(buckets[0]), 2)

    def test_comment_never_invokes_reducer(self):
        doc = {'kind': '评论', 'text': '父评。子评。'}
        def parser(raw, text, kind):
            self.assertEqual(kind, '评论')
            return raw, [{'start': 0, 'end': len(text), 'text': text}], []
        plan, segments, errors, calls, audit = m.reduce(doc, [], None, parser)
        self.assertEqual(len(segments), 1)
        self.assertEqual(calls, [])

    def test_missing_checked_keys_rejected(self):
        pp, errors = m.validate_map('真实原文。', {'D1': {}, 'D2': {}},
                                   {'checked_keys': ['D1'], 'proposals': []})
        self.assertTrue(errors)

    def test_model_chosen_anchors_order_only(self):
        text = '开头。甲户型。乙户型。'
        raw = {'units': [{'start_quote': q, 'start_occurrence': 1} for q in ['开头。', '乙户型。', '甲户型。']]}
        audit = []
        ordered, errors = m.order_literal_units(text, raw, audit)
        self.assertFalse(errors)
        self.assertEqual([u['start_quote'] for u in ordered['units']], ['开头。', '甲户型。', '乙户型。'])
        self.assertTrue(audit)
        self.assertEqual(len(ordered['units']), len(raw['units']))

    def test_whitespace_only_restore_not_fuzzy(self):
        source = '开头\u00a0真实原文。然后转到卧室。'
        unit = {'start_quote': '开头 真实原文。', 'start_occurrence': 1}
        audit = []
        m.restore_whitespace_anchor(source, unit, audit)
        self.assertEqual(unit['start_quote'], source)
        self.assertTrue(audit)
        wrong = {'start_quote': '开头改写原文。', 'start_occurrence': 1}
        m.restore_whitespace_anchor(source, wrong, audit)
        self.assertEqual(wrong['start_quote'], '开头改写原文。')

    def test_network_calls_share_global_gate(self):
        import delivery_v4 as base
        import tempfile, threading, time
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        lock = threading.Lock()
        state = {'active': 0, 'peak': 0}
        class Response:
            status_code = 200
            def json(self):
                return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}],
                        'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}}
        def network(*args, **kwargs):
            with lock:
                state['active'] += 1
                state['peak'] = max(state['peak'], state['active'])
            time.sleep(.01)
            with lock: state['active'] -= 1
            return Response()
        with tempfile.TemporaryDirectory(prefix='mr-gate-test-') as folder, patch.object(base, 'post_json', network):
            runner = base.ApiRunner(folder, concurrency=3, key='not-a-real-key')
            def call(i):
                return runner.call('test', {'i': i}, {'record_id': str(i), 'topic': base.T1, 'kind': '文章'},
                                   ['Map', 'Reduce', '校验'][i % 3])
            with ThreadPoolExecutor(max_workers=12) as pool:
                results = list(pool.map(call, range(18)))
        self.assertLessEqual(state['peak'], 3)
        self.assertEqual(len(results), 18)
        self.assertTrue(all(result[1]['status'] == 'success' for result in results))

if __name__ == '__main__': unittest.main()
