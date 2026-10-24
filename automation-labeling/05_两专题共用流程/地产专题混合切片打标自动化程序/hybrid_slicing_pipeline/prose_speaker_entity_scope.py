"""Comment header names are actors, not automatically property/project names.

A review trigger only. It never rewrites names or declares a replacement entity.
"""
import re


def issues(source,prose):
    source=str(source or '');prose=str(prose or '')
    names=set(re.findall(r'【(?:父评论|子评论\d*)｜([^】]+)】',source))
    body=re.sub(r'【(?:父评论|子评论\d*)｜[^】]*】','',source)
    out=[]
    for name in names:
        if not name or name in body:continue
        if re.search(re.escape(name)+r'(?:等|的)?(?:项目|房源|楼盘|小区|户型|房屋)',prose):
            out.append('摘要将原文发言者昵称“'+name+'”作为房源/项目对象；该名只见评论标题，须按实际评价对象重写')
    return out


INSTRUCTION='''评论标题中的speaker是人或账号昵称，不是房地产项目名称。
例如“【子评论｜甲】乙小区太贵”只能说明甲对乙价格的评价，不写成“甲房源价格高”。
可以说“评论者称/回复者称”，但评价对象须来自其正文事实，不把发言者名单变成楼盘名单。
昵称含房产或置业字样也不证明其为置业方、销售方或开发商。'''
