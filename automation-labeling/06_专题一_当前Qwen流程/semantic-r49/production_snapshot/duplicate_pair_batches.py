"""Bound duplicate-review context without changing article slice boundaries."""


def review_tasks(pairs, units, size=12):
    if type(size) is not int or size<1:raise ValueError('Positive batch size required')
    for start in range(0,len(pairs),size):
        group=pairs[start:start+size]
        used={p[k] for p in group for k in ('unit_a','unit_b')}
        yield {'pairs':group,'units':[u for u in units if u['unit_index'] in used]}
