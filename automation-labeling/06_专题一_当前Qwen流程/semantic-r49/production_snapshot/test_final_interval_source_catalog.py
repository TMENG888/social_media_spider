import unittest
import final_interval_source_catalog as sources


class FinalIdentityCatalogue(unittest.TestCase):
    def setUp(self):
        self.parts=['甲城央企中海海上雅苑的项目介绍','预售面积说明及免责声明','后文提到乙城乙项目']
        self.doc={'text':''.join(self.parts)};self.segments=[];start=0
        for i,text in enumerate(self.parts,1):
            self.segments.append({'id':i,'start':start,'end':start+len(text),'text':text});start+=len(text)
        self.units=[{'source_start_id':i,'source_end_id':i} for i in range(1,4)]

    def test_punctuation_free_text_respects_actual_final_boundaries(self):
        entries=sources.catalog(self.doc,self.units,self.segments)
        self.assertEqual(3,len(entries));self.assertEqual(self.parts,[e['text'] for e in entries])
        self.assertTrue(entries[0]['end']<=self.segments[0]['end'])
        self.assertEqual(self.doc['text'],''.join(e['text'] for e in entries))

    def test_later_identity_keeps_future_position(self):
        entries=sources.catalog(self.doc,self.units,self.segments)
        self.assertGreater(entries[-1]['end'],self.segments[1]['end'])

    def test_gap_or_overlap_rejected(self):
        self.units[1]['source_start_id']=1
        with self.assertRaises(ValueError):sources.catalog(self.doc,self.units,self.segments)

    def test_truncated_source_not_success(self):
        with self.assertRaises(ValueError):sources.catalog(self.doc,self.units[:-1],self.segments)


if __name__=='__main__':unittest.main()
