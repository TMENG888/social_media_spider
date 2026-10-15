import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import video_no_change as n

def sample():
    return {'fingerprint':'fp','article_key':'article','status':'retry_pending','retry_count':1,
            'last_error':'ASR_QUALITY_REVIEW_REQUIRED','updated_at':'old',
            'row':{'url':'https://example.invalid/video','title':'title','video_content':None,'captured_at':'old'},
            'comments':[{'comment_id':'c1','content':'retained'}]}
class NoChangeTests(unittest.TestCase):
    def pair(self):
        a=sample();b=copy.deepcopy(a);b.update(retry_count=2,updated_at='new');b['row']['captured_at']='new';return a,b
    def test_same_empty_subtitle_ends_with_evidence_not_success(self):
        a,b=self.pair();e=n.no_change_evidence(a,b,import_ok=True)
        self.assertEqual(e['disposition'],'no_change');self.assertFalse(e['accepted'])
        self.assertTrue(e['emptySubtitle']);self.assertEqual(e['beforeDigest'],e['afterDigest'])
    def test_unchanged_timestamp_without_attempt_not_evidence(self):
        a,b=self.pair();b['retry_count']=1
        self.assertIsNone(n.no_change_evidence(a,b,import_ok=True))
    def test_both_empty_on_login_memory_or_import_fault_not_complete(self):
        for error in ['LOGIN_REQUIRED','RESOURCE_MEMORY','MYSQL_IMPORT_FAILED','MKL MEMORY ALLOCATION']:
            a,b=self.pair();a['last_error']=b['last_error']=error
            self.assertIsNone(n.no_change_evidence(a,b,import_ok=True))
    def test_identity_change_and_new_content_not_unchanged(self):
        for change in [{'article_key':'other'},{'fingerprint':'other'},{'comments':[{'content':'new'}]}]:
            a,b=self.pair();b.update(change);self.assertIsNone(n.no_change_evidence(a,b,import_ok=True))
        a,b=self.pair();b['row']['video_content']='new';self.assertIsNone(n.no_change_evidence(a,b,import_ok=True))
    def test_previous_runtime_failure_not_content_baseline(self):
        a,b=self.pair();a['last_error']='MEMORY_RESOURCE_ERROR'
        self.assertIsNone(n.no_change_evidence(a,b,import_ok=True))
    def test_unrelated_failure_type_not_stable(self):
        a,b=self.pair();b['last_error']='DETAIL_UNAVAILABLE'
        self.assertIsNone(n.no_change_evidence(a,b,import_ok=True))
    def test_stop_or_import_failure_not_complete(self):
        a,b=self.pair()
        self.assertIsNone(n.no_change_evidence(a,b,import_ok=False))
        self.assertIsNone(n.no_change_evidence(a,b,import_ok=True,stopped=True))
    def test_same_verified_missing_detail_can_end(self):
        a,b=self.pair();a['last_error']=b['last_error']='DETAIL_UNAVAILABLE: target not observed after verified bounded exact search'
        self.assertEqual(n.no_change_evidence(a,b,import_ok=True)['failureKind'],'detail')
    def test_import_requires_exact_new_run_report(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'.state';folder.mkdir();file=folder/'asr_backfill_status.json'
            item={'keyword':'kw','fingerprint':'fp','retryObservationRunId':'run-new'}
            report={'retryRunId':'run-new','finishedAt':'now','keywords':[{'keyword':'kw','exactFingerprint':'fp','databaseImported':True,'status':'partial','finishedAt':'now'}]}
            file.write_text(json.dumps(report),encoding='utf-8');self.assertTrue(n.import_confirmed(root,item))
            for changed in [{'retryRunId':'old'},{'finishedAt':None}]:
                bad={**report,**changed};file.write_text(json.dumps(bad),encoding='utf-8');self.assertFalse(n.import_confirmed(root,item))
            for changed in [{'databaseImported':False},{'status':'failed'},{'exactFingerprint':'other'}]:
                bad={**report,'keywords':[{**report['keywords'][0],**changed}]}
                file.write_text(json.dumps(bad),encoding='utf-8');self.assertFalse(n.import_confirmed(root,item))
if __name__=='__main__':unittest.main()
