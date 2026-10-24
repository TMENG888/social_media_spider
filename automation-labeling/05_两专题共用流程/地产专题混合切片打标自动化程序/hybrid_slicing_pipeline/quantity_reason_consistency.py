"""Unsupported interpretation triggers; never calculate a replacement count."""
import re


def issue(tag, quote, reason):
    attribute = str(tag.get('l4') or tag.get('l3') or tag.get('emphasis') or '')
    if '数量' not in attribute:
        return None
    reason = str(reason or '')
    if re.search(r'非数量|不是数量|为入口形式|泛指存在|默认(?:为)?[一1]|按存在.{0,8}[一1]个', reason):
        return '数量解释依赖词义改判或存在性默认，原文计数依据未确认；不擅自确定为1或2'
    return None
