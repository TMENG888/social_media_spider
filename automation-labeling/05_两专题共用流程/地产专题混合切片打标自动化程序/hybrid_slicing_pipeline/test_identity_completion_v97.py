import copy
import unittest
from unittest.mock import patch
import identity_completion_v97 as m

class IdentityTests(unittest.TestCase):
 def setUp(self):
  self.business={'entities':[{'brand':'保利','entity':'保利发展'},{'brand':'保利','entity':'保利置业'},
                             {'brand':'金茂','entity':'中国金茂'}],
                 'projects':[{'id':'P01','name':'北京臻澐','role':'本品','aliases':['臻澐']}]}
  self.job={'kind':'文章','contexts':{'source':'金茂璞元的客厅。金茂开发本住宅。','title':'金茂璞元'},
            'units':[{'unit_id':'U1','text':'金茂璞元的客厅。','old':{'品牌组':'金茂','经营主体':'待判断','项目':'金茂璞元'},
                      'requested_fields':['经营主体']}]}
 def d(self,**kw):
  x={'unit_id':'U1','field':'经营主体','values':['中国金茂'],'source_keys':['source:8'],
     'mode':'canonical_alias','category':'supported','why':'金茂开发住宅，集团简称归一','confidence':.95}
  # Sentence boundary intentionally obtained from the real catalog.
  x['source_keys']=[m.catalog(self.job['contexts'])[1]['source_key']];x.update(kw);return x
 def test_canonical_alias(self): self.assertEqual(m.validate(self.d(),self.job,self.business),[])
 def test_ambiguous_poly_not_inferred(self):
  j=copy.deepcopy(self.job);j['contexts']={'source':'保利湖心墅，保利开发。'};j['units'][0]['old']['品牌组']='保利'
  self.assertTrue(m.validate(self.d(values=['保利发展'],source_keys=['source:0']),j,self.business))
 def test_end_identity_available(self):
  j=copy.deepcopy(self.job);j['contexts']={'source':'一层一境。项目名为保利湖心墅。'}
  j['units'][0].update(requested_fields=['项目'],text='一层一境。')
  self.assertFalse(m.validate(self.d(field='项目',values=['保利湖心墅'],source_keys=['source:5'],mode='source_context'),j,self.business))
 def test_missing_source_key(self): self.assertTrue(m.validate(self.d(source_keys=['invented']),self.job,self.business))
 def test_brand_conflict(self):
  j=copy.deepcopy(self.job);j['units'][0]['old']['品牌组']='保利'
  self.assertTrue(m.validate(self.d(),j,self.business))
 def test_property_relation_requires_review(self):
  d=self.d();c={'approve':True,'confidence':.99,'same_object':True,'all_objects_covered':True,
                'residential_identity':False,'no_identity_conflict':True}
  self.assertFalse(m.review_ok(d,c))
 def test_comment_parent_relation_two_sources(self):
  j=copy.deepcopy(self.job);j['kind']='评论';j['contexts']={'source':'泳池真不错','parent':'金茂开发金茂璞元。'}
  self.assertTrue(m.validate(self.d(source_keys=['parent:0'],mode='parent_relation'),j,self.business))
  self.assertFalse(m.validate(self.d(source_keys=['parent:0','source:0'],mode='parent_relation'),j,self.business))
 def test_comment_cannot_inherit_title(self):
  j=copy.deepcopy(self.job);j['kind']='评论'
  self.assertTrue(m.validate(self.d(source_keys=['title:0']),j,self.business))
 def test_multi_product_refused(self):
  j=copy.deepcopy(self.job);j['units'][0]['requested_fields']=['项目']
  self.assertTrue(m.validate(self.d(field='项目',values=['甲','乙']),j,self.business))
 def test_role_repeats_not_duplicate_tags(self):
  j=copy.deepcopy(self.job);j['units'][0]['requested_fields']=['项目角色']
  self.assertFalse(m.validate(self.d(field='项目角色',values=['非研究项目','非研究项目']),j,self.business))
 def test_negative_must_be_reviewed(self): self.assertFalse(m.review_ok(self.d(values=[]),None))
 def test_negative_reason_not_supported(self):
  self.assertFalse(m.review_ok(self.d(values=[]),{'approve':True,'confidence':.95,'category':'supported'}))
 def test_joint_id_name_role(self):
  rows=[{'unit_id':'U1','project_id':[],'项目名称':[],'项目角色':[],'原始摘录':'原文','标签明细':['VOC-X']}]
  ds=[self.d(field=f,values=v) for f,v in [('project_id',['P01']),('项目名称',['假名']),('项目角色',['本品'])]]
  out,changes,rejected=m.reconcile(rows,{'decisions':ds},self.business)
  self.assertEqual(out,rows);self.assertEqual(changes,[]);self.assertEqual(len(rejected),3)
 def test_preserve_nonempty_and_facts(self):
  rows=[{'unit_id':'U1','品牌组':'金茂','经营主体':'待判断','项目':'金茂璞元','原文摘录':'原文','标签明细':['VOC-X']}]
  baseline=copy.deepcopy(rows);out,cs,rs=m.reconcile(rows,{'decisions':[self.d()]},self.business)
  self.assertEqual(rows,baseline);self.assertEqual(out[0]['经营主体'],'中国金茂')
  self.assertEqual(out[0]['标签明细'],baseline[0]['标签明细']);self.assertEqual(out[0]['项目'],baseline[0]['项目'])
 def test_lossless_catalog(self):
  text='名字在任意长度边界'*50+'。尾部项目。';es=m.catalog({'source':text})
  self.assertEqual(''.join(e['text'] for e in es),text)
  self.assertTrue(all(text[e['start']:e['end']]==e['text'] for e in es))
 def test_duplicate_decisions_rejected(self): self.assertEqual(m.keyed([self.d(),self.d()]),{})
 def test_nonfinite_confidence_refused(self): self.assertFalse(m.confident(float('nan')))
 def test_ground_finds_actual_identity_not_nearby_key(self):
  j=copy.deepcopy(self.job);j['units'][0]['requested_fields']=['项目']
  d=self.d(field='项目',values=['金茂璞元'],source_keys=[m.catalog(j['contexts'])[1]['source_key']])
  grounded=m.ground(d,j,self.business)
  self.assertNotEqual(grounded['source_keys'],d['source_keys']);self.assertFalse(m.validate(grounded,j,self.business))
  lookup={e['source_key']:e for e in m.catalog(j['contexts'])}
  self.assertTrue(all('金茂璞元' in lookup[k]['text'] for k in grounded['source_keys']))
 def test_ground_never_brand_infers_poly_branch(self):
  j=copy.deepcopy(self.job);j['contexts']={'source':'保利湖心墅，保利开发。'}
  d=m.ground(self.d(values=['保利发展']),j,self.business)
  self.assertEqual(d['values'],[]);self.assertEqual(d['category'],'ambiguous_entity')
 def test_schema_only_requested_roles(self):
  j=copy.deepcopy(self.job);j['units'][0]['requested_fields']=['项目角色'];j['units'][0]['old']={'项目角色':[]}
  s=m.schema_for(j,self.business,True)
  self.assertEqual(s['properties']['checks']['items']['properties']['field']['enum'],['项目角色'])
 def test_orphan_role_refused(self):
  rows=[{'unit_id':'U1','project_id':[],'项目名称':[],'项目角色':[]}]
  out,cs,rs=m.reconcile(rows,{'decisions':[self.d(field='项目角色',values=['本品'])]},self.business)
  self.assertEqual(cs,[]);self.assertEqual(out,rows);self.assertTrue(rs)
 def test_production_adapter_preserves_labels_boundaries_and_prose(self):
  import delivery_v4 as b
  result={'document':{'record_id':'R1','topic':b.T1,'kind':'文章','text':'金茂璞元。','title':'金茂璞元'},
    'rows':[{'unit_id':'U1','品牌组':'金茂','经营主体':'待判断','项目':'金茂璞元','原文摘录':'金茂璞元。',
             '标签明细':['VOC-X'],'具体产品做法':'原做法','备注':'原待核'}],
    'traces':[{'unit_id':'U1','起点':0,'终点':5}],'pending_units':[{'unit_id':'U1','旧单元':{'经营主体':'待判断'}}],
    'calls':[],'audit':[]}
  original=copy.deepcopy(result)
  with patch.object(m,'resolve',return_value={'decisions':[self.d()],'remaining':[],'calls':[],'audit':[]}):
   out=m.process(result,self.business,None)
  self.assertEqual(result,original);self.assertEqual(out['document'],original['document'])
  self.assertEqual(out['rows'][0]['经营主体'],'中国金茂');self.assertEqual(out['rows'][0]['标签明细'],['VOC-X'])
  self.assertEqual(out['rows'][0]['具体产品做法'],'原做法');self.assertEqual(out['rows'][0]['备注'],'原待核')
  self.assertEqual(out['pending_units'][0]['旧单元']['经营主体'],'中国金茂')
  self.assertEqual(out['traces'][0]['起点'],0);self.assertEqual(out['traces'][0]['终点'],5)
 def test_default_launcher_and_export_only_boundary(self):
  from pathlib import Path
  code=Path(__file__).with_name('run_bulk_v96.ps1').read_text(encoding='utf-8')
  start=code.index('if(-not $FinalizeOnly){');end=code.index('# FinalizeOnly never')
  self.assertIn('apply_identity_completion_v97.py',code[start:end])
  self.assertNotIn('apply_identity_completion_v97.py',code[end:])
  package=Path(__file__).with_name('package_bulk_v96.py').read_text(encoding='utf-8')
  self.assertIn("trace.get('归属补全-v97')",package)

if __name__=='__main__': unittest.main()
