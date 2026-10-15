import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from production_output_publisher import flush
class FakeRedis:
    seen=set();records=[]
    def __init__(self,*a,**k):pass
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def command(self,*args):
        assert args[0]=='EVAL'
        eid=args[6]
        if eid in self.seen:return 0
        self.seen.add(eid);self.records.append(args);return 1
class BrokenRedis(FakeRedis):
    def __enter__(self):raise TimeoutError()
class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='wechat-output-publisher-test-'))
        (self.root/'pending').mkdir();FakeRedis.seen.clear();FakeRedis.records.clear()
        self.event={'eventId':'unit-event','readbackVerified':True,'runId':'unit-original-run','generation':'unit-gen','computer':'test','worker':'test-worker','committedAt':'2026-10-12T00:00:00Z','items':[{'types':['subtitle']}],'verification':[{'hash':'private-check'}]}
    def save(self):
        p=self.root/'pending/unit-event.json';p.write_text(json.dumps(self.event),encoding='utf-8');return p
    def test_failure_preserves_and_replays(self):
        p=self.save();r=flush(self.root,'redis://unused',None,BrokenRedis)
        self.assertTrue(r['deferred']);self.assertTrue(p.exists())
        r=flush(self.root,'redis://unused',None,FakeRedis)
        self.assertEqual(r['sent'],1);self.assertTrue((self.root/'sent/unit-event.json').exists())
        self.assertIn('unit-original-run',FakeRedis.records[0][3])
        self.assertNotIn('verification',FakeRedis.records[0][7])
    def test_repeated_delivery_is_deduplicated(self):
        self.save();flush(self.root,'redis://unused',None,FakeRedis)
        self.save();r=flush(self.root,'redis://unused',None,FakeRedis)
        self.assertEqual(r['deduplicated'],1);self.assertEqual(len(FakeRedis.records),1)
    def test_unverified_never_sent(self):
        self.event['readbackVerified']=False;self.save()
        r=flush(self.root,'redis://unused',None,FakeRedis)
        self.assertEqual(r['sent'],0);self.assertEqual(len(FakeRedis.records),0)
if __name__=='__main__':unittest.main()
