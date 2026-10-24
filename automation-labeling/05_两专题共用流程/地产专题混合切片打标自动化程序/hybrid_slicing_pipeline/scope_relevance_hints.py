"""Soft anti-exclusion hints, not output slicing or automatic tag selection."""
import re


def exclusion_review_hint(topic,text):
    clean=re.sub(r'【[^】]*】','',text)
    if topic=='北京臻澐项目口碑':
        if re.search(r'等等党|挑花眼|继续观望|纠结.{0,15}(?:买|选|等)|感觉这个也不错',clean):
            return '存在选择评价或观望态度，不需要产品参数；不得直接排除，保留整条按客户/观点定义核验'
        if re.search(r'(?:体育场|体育馆|学校|公园|道路|地铁|医院|商场).{0,18}规划',clean):
            return '存在周边公共配套规划事实或提问；需识别研究上下文与问题性质，不直接排除或确认规划已经落地'
    if re.search(r'\d+\s*层.{0,6}洋房|(?:建面|建筑面积).{0,12}\d+\s*(?:㎡|平|米)',clean):
        return '营销内容混有明确住宅参数/形态，不能整条当纯邀请排除；保留现有事实继续定义核验'
    return None
