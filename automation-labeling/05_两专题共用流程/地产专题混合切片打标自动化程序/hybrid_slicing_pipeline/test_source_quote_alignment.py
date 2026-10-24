import unittest
from source_quote_alignment import quote_spans

class Alignment(unittest.TestCase):
    def test_nbsp_is_source_preserving(self):
        source='开头\u00a0户型。下一个项目'
        self.assertEqual([(0,6)],quote_spans(source,'开头 户型。'))
        self.assertEqual('开头\u00a0户型。',source[slice(*quote_spans(source,'开头 户型。')[0])])
    def test_wording_and_punctuation_not_guessed(self):
        self.assertEqual([],quote_spans('采用新风，设茶室','采用新风。设茶室'))
        self.assertEqual([],quote_spans('客厅宽5米','客厅宽6米'))
    def test_repeated_quotes_not_arbitrarily_selected(self):
        self.assertEqual([(0,3),(4,7)],quote_spans('甲\u00a0乙。甲\u00a0乙','甲 乙'))

if __name__=='__main__':unittest.main()
