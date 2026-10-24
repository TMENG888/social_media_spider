"""Role statements need source-body evidence, not account-name clues."""
import re

ROLE_GROUPS=(
    (r'置业顾问|房产顾问|销售顾问|售楼员|售楼人员|销售人员|房产经纪(?:人)?|经纪人|中介',
     r'置业顾问|房产顾问|销售顾问|售楼员|售楼人员|销售人员|房产经纪(?:人)?|经纪人|中介'),
    (r'自媒体(?:账号|博主)?',r'自媒体(?:账号|博主)?'),
    (r'置业方|销售方|房产方|开发方',r'置业方|销售方|房产方|开发方'),
)


def issues(source,prose):
    body=re.sub(r'【(?:父评论|子评论\d*)｜[^】]*】','',str(source or ''))
    prose=str(prose or '');out=[]
    for asserted,support in ROLE_GROUPS:
        match=re.search(asserted,prose)
        if match and not re.search(support,body):
            out.append('摘要认定'+match.group(0)+'职业/账号性质，但当前正文未明示；账号昵称或房产字样不足证明，改为评论者/回复者')
    return out
