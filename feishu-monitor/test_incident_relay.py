import importlib.util
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
spec=importlib.util.spec_from_file_location('incident_relay',Path(__file__).with_name('incident-relay.py'))
relay=importlib.util.module_from_spec(spec);spec.loader.exec_module(relay)

class FakeRedis:
    def __init__(self):
        self.cursor=None;self.receipts=[]
        self.event={'kind':'captcha','platform':'测试平台','machine':'TEST','workerId':'fixture',
            'status':'manual_required','incidentId':'TEST-incident','keyword':'非真实故障'}
    def command(self,*p):
        if p[0]=='EVAL':
            if p[1]==relay.LEASE:return 1
            self.cursor=p[6];self.receipts.append(json.loads(p[7]));return 1
        if p[0]=='HGET':return self.cursor
        if p[0]=='HVALS':return [] if self.cursor else [json.dumps(self.event)]
        raise AssertionError(p[0])

class IncidentRelayTests(unittest.TestCase):
    def test_confirmed_only_commit_and_no_duplicate(self):
        c=FakeRedis();calls=[]
        send=lambda *p:calls.append(p) or True
        self.assertEqual(relay.deliver_source(c,'fixture','token','unused',sender=send)['delivered'],1)
        self.assertEqual(relay.deliver_source(c,'fixture','token','unused',sender=send)['delivered'],0)
        self.assertEqual(len(calls),1);self.assertTrue(c.receipts[0]['deliveryConfirmed'])
    def test_send_failure_or_unconfirmed_never_advance(self):
        for send in (lambda *p:False,lambda *p:(_ for _ in ()).throw(RuntimeError('offline'))):
            c=FakeRedis()
            with self.assertRaises(RuntimeError):relay.deliver_source(c,'fixture','token','unused',sender=send)
            self.assertIsNone(c.cursor);self.assertEqual(c.receipts,[])
    def test_plain_text_card_no_raw_error_or_claimed_recovery(self):
        e=FakeRedis().event;e['error']='SECRET-NOT-ALLOWED'
        p=relay.payload(e);self.assertNotIn('SECRET-NOT-ALLOWED',json.dumps(p))
        e['status']='resolved';self.assertIn('人工已确认',json.dumps(relay.payload(e),ensure_ascii=False))

    def test_database_fault_card_is_sanitized_and_not_a_captcha_instruction(self):
        e={**FakeRedis().event,'kind':'database','errorCode':'ECONNREFUSED','stage':'connect',
           'error':'SECRET-PASSWORD','target':{'host':'SECRET-HOST'},'status':'active'}
        text=json.dumps(relay.payload(e),ensure_ascii=False)
        self.assertIn('ECONNREFUSED',text);self.assertIn('数据库回读异常',text)
        self.assertNotIn('SECRET',text);self.assertNotIn('确认人工处理',text)
        e.update(status='resolved',databaseReadbackVerified=False)
        self.assertNotIn('数据库真实查询已恢复',json.dumps(relay.payload(e),ensure_ascii=False))
        e['databaseReadbackVerified']=True
        self.assertIn('数据库真实查询已恢复',json.dumps(relay.payload(e),ensure_ascii=False))

    def test_database_delivery_uses_existing_confirmed_receipt_and_dedup(self):
        c=FakeRedis();c.event.update(kind='database',errorCode='ECONNREFUSED',stage='connect',status='active')
        calls=[]
        self.assertEqual(relay.deliver_source(c,'fixture','token','unused',sender=lambda *a:calls.append(a) or True)['delivered'],1)
        self.assertEqual(relay.deliver_source(c,'fixture','token','unused',sender=lambda *a:self.fail('duplicate'))['delivered'],0)
        self.assertEqual(len(calls),1)

if __name__=='__main__':unittest.main()
