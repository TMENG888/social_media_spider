"""Separate superseded branch evidence failures from unresolved final issues.

Only exact, per-key branch quote failures may resolve after a final grounded
positive decision or a high-confidence explicit unsupported decision. Keep
structural failures, semantic conflicts and missing protocol visible.
"""
PREFIXES=('支持证据无法逐字定位：','对象证据无法定位：')


def partition(issues,resolved_keys):
    active=[];resolved=[]
    for issue in issues:
        key=None
        if isinstance(issue,str):
            for prefix in PREFIXES:
                if issue.startswith(prefix):key=issue[len(prefix):];break
        if key is not None and key in resolved_keys:resolved.append(issue)
        else:active.append(issue)
    return active,resolved
