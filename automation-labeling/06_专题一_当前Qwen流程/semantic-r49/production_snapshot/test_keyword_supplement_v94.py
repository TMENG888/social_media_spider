import copy
import unittest
import keyword_supplement_v94 as k


class KeywordFallbackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tax=k.core.base.load_taxonomy(k.core.DEFAULT_TAXONOMY)
        cls.index=k.core.index_for(cls.tax,k.core.base.T1)

    def result(self,text):
        uid='T1-fixture-M001'
        return {'document':{'record_id':'T1-fixture','topic':k.core.base.T1,'kind':'文章','text':text,
                'semantic_segments':[{'id':1,'start':0,'end':len(text),'text':text}]},
            'rows':[{'unit_id':uid,'标签明细':[],'打标说明':'既有说明','具体产品做法':'原有做法','备注':'原备注','验收状态':'需人工审核'}],
            'traces':[{'unit_id':uid,'起点':0,'终点':len(text)}],
            'pending_units':[],'complete':False,'label_supplement_events':[],
            'label_supplement_deferred':[], 'label_supplement_coverage':{'all_candidates_adjudicated':False}}

    def check(self,text,key,want):
        result=self.result(text);unit=k.core.audit_units(result)[0]
        rule=k.compile_rule(key,self.index[key]);hits=k.find_hits(unit,rule)
        direct=any(not k.hit_issues(h,rule,unit,result) for h in hits)
        self.assertEqual(direct,want,(text,key,hits))

    def test_club_pool_explicit(self):self.check('项目会所设有游泳池。','D0384',True)
    def test_club_pool_alias(self):self.check('会所配备25米恒温泳池。','D0384',True)
    def test_traditional(self):self.check('會所設有游泳池。','D0384',True)
    def test_park_is_not_club(self):self.check('体育公园内设置游泳池。','D0384',False)
    def test_separate_object_same_sentence(self):self.check('会所设茶室，体育公园设有泳池。','D0384',False)
    def test_separate_sentences(self):self.check('会所设有茶室。附近公共泳池开放。','D0384',False)
    def test_external_pool(self):self.check('会所旁边的公共泳池已开放。','D0384',False)
    def test_reverse_object(self):self.check('泳池旁另设会所。','D0384',False)
    def test_parallel_facilities(self):self.check('小区设有会所和游泳池。','D0384',False)
    def test_another_project(self):self.check('甲会所设茶室，另一个楼盘配有游泳池。','D0384',False)
    def test_negation(self):self.check('会所没有游泳池。','D0384',False)
    def test_question(self):self.check('会所有游泳池吗？','D0384',False)
    def test_wish(self):self.check('希望会所配有泳池。','D0384',False)
    def test_condition(self):self.check('如果会所配有泳池就好了。','D0384',False)
    def test_plan_preserved(self):self.check('规划会所将设置游泳池。','D0384',True)
    def test_speakers_not_combined(self):self.check('【父评论｜甲】会所不错【子评论1｜乙】有游泳池','D0384',False)
    def test_kitchen_own_aircon(self):self.check('厨房配备独立空调。','D0251',True)
    def test_kitchen_cannot_borrow_living_aircon(self):self.check('厨房有冰箱，客厅配备空调。','D0251',False)
    def test_kitchen_after_living_aircon(self):self.check('客厅配备空调，厨房有冰箱。','D0251',False)
    def test_bedroom_not_total_width(self):self.check('主卧面宽17米。','D0184',False)
    def test_chinese_width(self):self.check('户型面宽十二米。','D0184',True)
    def test_decimal_area(self):self.check('户型建筑面积120.5㎡。','D0186',True)
    def test_usable_area_not_gross(self):self.check('户型实用面积120㎡。','D0186',False)
    def test_disclaimer_only(self):self.check('以上面积均为建筑面积。','D0186',False)
    def test_actual_chinese_count(self):self.check('户型有两个厨房。','D0198',True)
    def test_independent_housekeeping(self):self.check('户型有一个独立家政间。','D0220',True)
    def test_quantity_cannot_default_one(self):self.check('主卧面积30㎡。','D0210',False)
    def test_equipment_count_not_room_count(self):self.check('购买了两个厨房电器。','D0198',False)
    def test_extremely_high_efficiency_not_tower(self):self.check('户型拥有超高得房率。','D0172',False)
    def test_far_better_than_high_rise(self):self.check('园林的居住舒适度远超高层社区。','D0172',False)
    def test_villa_comparison(self):self.check('主卧面积60㎡，尺度堪比独栋别墅。','D0168',False)
    def test_wished_property_type(self):self.check('适合追求低密洋房自住的家庭。','D0169',False)
    def test_excludes_shops(self):self.check('规划不含回迁、底层商铺。','D0175',False)
    def test_total_project_area(self):self.check('小区概况占地面积3.1万㎡建筑面积7.8万㎡。','D0186',False)
    def test_plot_gross_area(self):self.check('该宗地地上建筑面积约10.7万平方米。','D0186',False)
    def test_home_area_not_landscape_area(self):self.check('花园建筑规划打造建筑面积145-260㎡的四代住宅。','D0403',False)
    def test_garden_no_numerical_area(self):self.check('249㎡户型打造双花园，观景尺度更极致。','D0403',False)
    def test_balcony_depth_not_home_depth(self):self.check('进深不大于1.8米的阳台可享受面积计算优惠。','D0185',False)
    def test_garden_area_explicit(self):self.check('社区园林面积约8000㎡。','D0403',True)
    def test_shared_facade_window_material(self):self.check('外墙、门窗采用高端隔音隔热材质。','D0416',True)
    def test_history_refusal_blocks(self):
        result=self.result('会所设有游泳池。');uid=result['rows'][0]['unit_id']
        result['label_supplement_events']=[{'unit_id':uid,'key':'D0384','处理':'历史否决','verdict':'unsupported','confidence':.99,'原因':'对象不符'}]
        unit=k.core.audit_units(result)[0];rule=k.compile_rule('D0384',self.index['D0384'])
        self.assertTrue(k.hit_issues(k.find_hits(unit,rule)[0],rule,unit,result))
    def test_additive_and_idempotent(self):
        source=self.result('项目会所设有游泳池及茶室。')
        original=copy.deepcopy(source);once=k.process(source,self.tax);twice=k.process(once,self.tax)
        self.assertEqual(source,original)
        self.assertEqual(once['rows'],twice['rows'])
        self.assertEqual(once['keyword_supplement_events'],twice['keyword_supplement_events'])
        ids=[t['标签路径ID'] for t in once['rows'][0]['标签明细']]
        self.assertIn('VOC-0384',ids);self.assertIn('VOC-0380',ids);self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(once['rows'][0]['具体产品做法'],'原有做法')
        for proof in once['traces'][0]['关键词补标证据']:
            for span in proof['attribute_spans']+proof['keyword_matches']:
                self.assertEqual(original['document']['text'][span['start']:span['end']],span['quote'])
    def test_all_dictionary_directions_compiled(self):
        for topic,count in [(k.core.base.T1,323),(k.core.base.T2,580)]:
            index=k.core.index_for(self.tax,topic);self.assertEqual(len(index),count)
            self.assertTrue(all(k.compile_rule(key,tag)['groups'] for key,tag in index.items()))


if __name__=='__main__':unittest.main()
