"""Presentation-only exclusions. Never remove tasks or real aggregate counts."""

def reportable_worker(name):
    name=str(name or '').rsplit('/',1)[-1]
    return name!='worker-local-test' and not name.startswith('worker-local-test-')

def reporting_snapshot(snapshot):
    """Defensive filtering for previews/signatures built from older snapshots."""
    result=dict(snapshot)
    result['workers']=[w for w in snapshot.get('workers',[]) if reportable_worker(w.get('worker'))]
    result['recentErrors']=[e for e in snapshot.get('recentErrors',[]) if reportable_worker(e.get('worker'))]
    if 'productionOutputs' in snapshot:
        outputs=dict(snapshot['productionOutputs'])
        for key in ('latest','perWorker'):
            outputs[key]=[r for r in outputs.get(key,[]) if reportable_worker(r.get('worker'))]
        # Actual committed test data remains in global hourly/database totals.
        result['productionOutputs']=outputs
    return result
