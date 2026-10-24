import unittest
from verify_observed_asr_identity_cases import inspect


class ObservedAnchors(unittest.TestCase):
    def fixture(self):
        return {'results':[
            {'document':{'record_id':'T1-316877139627506490'},'rows':[
                {'原文摘录':'有的用的环保材料这个是竹竹桃楠的竹竹，厨房的窗户也很大',
                 '具体产品做法':'部分装修使用环保材料，厨房设置较大窗户；材料具体名称无法确认。'}]},
            {'document':{'record_id':'T1-8000912876517502274'},'rows':[
                {'原文摘录':'建筑面积约210-370㎡','品牌组':'中海','项目':'中海安澜北京','城市':'北京'}]}]}

    def test_absent_sources_do_not_pass(self):
        self.assertEqual(2,len(inspect({'results':[]})['errors']))

    def test_empty_practice_is_not_a_fix(self):
        data=self.fixture();data['results'][0]['rows'][0]['具体产品做法']=''
        self.assertIn('模糊ASR仍保留明确环保材料和厨房窗户事实',inspect(data)['errors'])

    def test_observed_material_guess_is_detected(self):
        data=self.fixture();data['results'][0]['rows'][0]['具体产品做法']='采用竹材等环保材料，厨房窗户较大。'
        self.assertIn('ASR疑词不确定化为全屋风格竹材或过滤窗安装',inspect(data)['errors'])

    def test_lost_identity_is_detected(self):
        data=self.fixture();data['results'][1]['rows'][0]['项目']='待判断'
        self.assertIn('明确单项目文章面积切片保留可核身份',inspect(data)['errors'])

    def test_hypothetical_corrected_anchor_is_accepted(self):
        # A test fixture is not a generated delivery or a measured accuracy result.
        self.assertFalse(inspect(self.fixture())['errors'])


if __name__=='__main__':unittest.main()
