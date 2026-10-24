"""Record and check accepted cache hashes around the authorized retry."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).parent
sys.stdout.reconfigure(encoding='utf8')
guard=ROOT/'accepted_476_before_repair.json'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
if sys.argv[1]=='freeze':
    assert not guard.exists(),'Existing retry baseline must not be overwritten'
    status=json.loads((ROOT/'status.json').read_text(encoding='utf8'))
    assert status['finished'] and status['completed']==476 and status['failed']==24
    hashes={p.name:digest(p) for p in (ROOT/'sources').glob('*.json')}
    assert len(hashes)==476
    guard.write_text(json.dumps({'hashes':hashes,'failures':status['errors']},ensure_ascii=False,indent=2),encoding='utf8')
    print('Frozen 476 accepted source hashes and 24 retry targets')
else:
    baseline=json.loads(guard.read_text(encoding='utf8'))
    for name,h in baseline['hashes'].items():assert digest(ROOT/'sources'/name)==h,name
    print('All 476 accepted source cache files are unchanged')
