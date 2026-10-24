import unittest
from verify_observed_label_target_v59 import inspect

class ObservedLabelTargetTests(unittest.TestCase):
    def row(self,quote,tags):return {'原始摘录':quote,'标签明细':[{'标签路径ID':t} for t in tags]}
    def fixture(self):
        return {'results':[
            {'document':{'record_id':'T2-8000912876517503117'},'rows':[
                self.row('4室2厅3卫，专属家政套房，四居洋房',['VOC-0169']),
                self.row('低密洋房',[])]},
            {'document':{'record_id':'T2-2188228096999350274'},'rows':[
                self.row('王府中式园林',['VOC-0401']),
                self.row('三园十八景',['VOC-0401'])]}]}
    def test_missing_sources_fail(self):self.assertEqual(len(inspect({'results':[]})['errors']),2)
    def test_corrected_target_fixture(self):self.assertFalse(inspect(self.fixture())['errors'])
    def test_repetition_and_cross_object_are_detected(self):
        d=self.fixture();d['results'][0]['rows'][1]['标签明细']=[{'标签路径ID':'VOC-0169'}]
        d['results'][1]['rows'][1]['标签明细']=[{'标签路径ID':'VOC-0229'}]
        self.assertEqual(len(inspect(d)['errors']),3)

if __name__=='__main__':unittest.main()
