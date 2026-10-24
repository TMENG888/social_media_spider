"""Known false review warnings: absence of '我' is not negative evidence.

Returning supported here means no program hard contradiction; it does not
select a tag and still requires the independent semantic definition review.
"""
import unittest
from delivery_v6 import evidence_guard


class PronounRegressions(unittest.TestCase):
    def tag(self, attribute, level='购房关注点'):
        return {'l1': '客户', 'l2': '购房决策', 'l3': level,
            'l4': attribute, 'emphasis': attribute}

    def test_actual_traffic_criticism_does_not_require_pronoun(self):
        state, _ = evidence_guard('交通是短板，去西四环要经过四个红绿灯。', self.tag('交通配套'))
        self.assertEqual('supported', state)

    def test_actual_price_criticism_does_not_require_pronoun(self):
        state, _ = evidence_guard('第二价格太高了说要13万', self.tag('价格'))
        self.assertEqual('supported', state)

    def test_actual_residence_statement_without_pronoun(self):
        state, _ = evidence_guard('在玉海园住了四年了', self.tag('当前居住楼盘', '居住现状'))
        self.assertEqual('supported', state)

    def test_quote_price_is_not_personal_budget(self):
        state, _ = evidence_guard('第二价格太高了说要13万', self.tag('总价预算'))
        self.assertEqual('rejected', state)

    def test_asking_price_is_not_homeownership(self):
        state, _ = evidence_guard('这个房子多少钱？', self.tag('购房/租房', '居住现状'))
        self.assertEqual('rejected', state)

    def test_noise_complaint_is_not_purchase_motivation(self):
        tag = self.tag('通勤')
        tag['l2'] = '购房动机'
        self.assertEqual('rejected', evidence_guard('这里飞机噪音很大', tag)[0])


if __name__ == '__main__':unittest.main()
