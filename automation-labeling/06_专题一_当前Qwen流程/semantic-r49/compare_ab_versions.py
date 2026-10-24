import json,sys
from pathlib import Path
R=Path(__file__).parent
def read(p):return json.loads(p.read_text(encoding='utf8'))
out={}
version=sys.argv[1] if len(sys.argv)>1 else 'r23'
for b in ['A','B']:
    old={r['document']['source_id']:r for r in read(R/'run_r22'/f'{b}_results.json')}
    new={r['document']['source_id']:r for r in read(R/f'run_{version}'/f'{b}_results.json')}
    assert old.keys()==new.keys()
    changes=[]
    for sid in old:
        fields=['原文摘录','起点','终点','品牌组','经营主体','城市','发布者角色','具体产品做法','创新类型','创新等级','创新依据','标签明细']
        for f in fields:
            if [r.get(f) for r in old[sid]['rows']]!=[r.get(f) for r in new[sid]['rows']]:changes.append([sid,f])
        assert [(p['start'],p['end']) for p in old[sid]['semantic_partition']]==[(p['start'],p['end']) for p in new[sid]['semantic_partition']]
    assert not changes,changes
    calls=read(R/f'run_{version}'/f'{b}_run.json')['calls']
    out[b]={'sources':len(new),'semantic_field_changes':changes,'calls':len(calls),'cache_hits':sum(bool(c.get('cache_hit')) for c in calls),'new_api_calls':sum(not c.get('cache_hit') for c in calls)}
(R/f'run_{version}'/'compare_AB_versions.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(out,ensure_ascii=False))
