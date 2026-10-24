import copy
import unittest
import literal_comment_name_key_protocol as protocol


class NameKeys(unittest.TestCase):
    def setUp(self):
        self.source='【父评论｜湖岸苑销售】我住南湖雅苑，我们和西湖新城一个在东边一个在西边。'
        self.catalog=protocol.legacy.sources.source_catalog(self.source)
        key=next(e['source_key'] for e in self.catalog if '我住' in e['text'])
        self.response={'mentions':[{'name':name,'name_source_key':key,'why':'正文明确居住小区的对比','confidence':.95}
            for name in ('南湖雅苑','西湖新城')],'coverage_complete':True,'confidence':.95}

    def test_two_names_share_exact_original_not_reconstructed_quote(self):
        original=copy.deepcopy(self.response)
        targets,issues=protocol.validate(self.response,self.catalog,[])
        self.assertFalse(issues);self.assertEqual(2,len(targets));self.assertEqual(original,self.response)
        self.assertTrue(all('我住南湖雅苑' in t['comment_quote'] for t in targets))
        self.assertTrue(all('id' not in t and 'sentiment' not in t for t in targets))

    def test_old_quote_never_silently_retrofitted(self):
        self.response['mentions'][0].update(quote='我们住南湖雅苑',source_key=self.catalog[0]['source_key'])
        self.assertTrue(protocol.validate(self.response,self.catalog,[])[1])

    def test_nickname_not_evidence(self):
        self.response['mentions'][0]['name']='湖岸苑'
        self.assertTrue(protocol.validate(self.response,self.catalog,[])[1])

    def test_unknown_key_rejected(self):
        self.response['mentions'][0]['name_source_key']='SRC-FABRICATED'
        self.assertTrue(protocol.validate(self.response,self.catalog,[])[1])

    def test_low_confidence_still_rejected(self):
        self.response['mentions'][0]['confidence']=.8
        self.assertTrue(protocol.validate(self.response,self.catalog,[])[1])


if __name__=='__main__':unittest.main()
