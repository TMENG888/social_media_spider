"""Verify direct comment names without requiring redundant parent evidence.

Does not select projects or assign tags/sentiment. Used only to verify a model
proposal; implicit references still require independently checked parent text.
"""
import re


def direct_name_supported(name, quote, comment_text, projects):
    compact=lambda value: re.sub(r'\s+','',str(value or ''))
    name=compact(name);quote=compact(quote);comment_text=compact(comment_text)
    # A display name such as 臻澐销售 is not a project statement in the comment.
    author_marker=r'【(?:父评论|子评论\d*)[｜|][^】]*】'
    quote=re.sub(author_marker,'',quote)
    comment_text=re.sub(author_marker,'',comment_text)
    if not name or not quote or quote not in comment_text:
        return False
    matches=[p for p in projects if name in [compact(p.get('name'))]+[compact(a) for a in p.get('aliases',[])]]
    if len(matches)>1:
        return False
    if not matches:
        return name in quote  # retain grounded external names; never create IDs
    project=matches[0]
    aliases=[compact(project.get('name'))]+[compact(a) for a in project.get('aliases',[])]
    for alias in aliases:
        if not alias or alias not in quote:
            continue
        owners=[p for p in projects if alias in [compact(p.get('name'))]+[compact(a) for a in p.get('aliases',[])]]
        if len(owners)==1:
            return True
    return False
