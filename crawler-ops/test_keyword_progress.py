import json,unittest
from unittest.mock import patch
import keyword_progress as kp

class ProgressTests(unittest.TestCase):
 def test_current_manifest_only_and_distinct_outcomes(self):
  tasks=[{'topic':'专题一','keyword':k,'redisTaskId':k} for k in ['new','retry','done','backlog','expired']]+[{'topic':'专题二','keyword':'other','redisTaskId':'other'}]
  values={'statuses':['pending','pending','completed','completed','leased'],'attempts':['0','2','1','1','1'],'owners':[None]*5,'results':[None,None,'{}','{"pendingImport":true}',None],'errors':[None]*5}
  calls=[]
  def hgets(c,ns,f,ids):calls.append(ids);return values[f]
  class Connection:
   def command(self,*args):return ['expired','500']
  with patch.object(kp,'read_json',side_effect=[{'tasks':tasks},{}]),patch.object(kp,'hgets',side_effect=hgets):p=kp.observe(Connection(),'test','小红书',1)
  self.assertEqual(p['total'],5);self.assertTrue(all(ids==['new','retry','done','backlog','expired'] for ids in calls))
  self.assertEqual([r['status'] for r in p['rows']],['pending','retry','completed','pending_import','expired'])
  p=kp.enrich(p,[]);self.assertEqual(p['completed'],2);self.assertEqual(p['percent'],40)
  self.assertTrue(all('_owner' not in r for r in p['rows']))
 def test_duplicate_worker_names_do_not_guess_machine(self):
  def row(owner):return {'status':'leased','keyword':'住宅','_owner':owner}
  machines=[{'computer':c,'machine':c,'keyword':'住宅','status':'collecting','worker':'worker-01'} for c in ['A','B']]
  p=kp.enrich({'rows':[row('worker-01')],'total':1},machines)
  self.assertNotIn('machine',p['rows'][0]);self.assertEqual(p['rows'][0]['status'],'leased')
  p=kp.enrich({'rows':[row('A/worker-01')],'total':1},machines)
  self.assertEqual(p['rows'][0]['machine'],'A')
 def test_changing_state_is_not_false_completion(self):
  task={'topic':'专题一','keyword':'x','redisTaskId':'x'}
  values=iter([['leased'],['1'],['owner'],['{}'],[None],['completed']])
  class Connection:
   def command(self,*args):return []
  with patch.object(kp,'read_json',side_effect=[{'tasks':[task]},{}]),patch.object(kp,'hgets',side_effect=lambda *a:next(values)):
   p=kp.enrich(kp.observe(Connection(),'ns','抖音',1),[])
  self.assertEqual(p['completed'],0);self.assertEqual(p['rows'][0]['status'],'updating')
 def test_read_failure_keeps_words_unknown(self):
  with patch.object(kp,'read_json',return_value={'tasks':[{'keyword':'k','order':1}]}):p=kp.enrich(kp.unavailable('小红书'),[])
  self.assertEqual(p['source'],'unavailable');self.assertEqual(p['counts'],{'unknown':1})

if __name__=='__main__':unittest.main(verbosity=2)
