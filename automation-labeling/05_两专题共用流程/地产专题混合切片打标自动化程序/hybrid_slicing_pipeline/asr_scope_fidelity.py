"""Staged source-only ambiguity alarms; never generates substitute prose/tags."""
import re


INSTRUCTION='''
转录中对象、材质名或完成状态不清，不能靠行业常识纠正成确定配置。
某件家具的风格不代表全屋装修风格；预留、装不完、只完成一部分不代表已全部安装。
不清楚的重复音节不等于材料名，只保留明确的环保材料等事实，具体猜测留审核备注。
原文拼写不清的品牌不得还原为知名品牌；看不出材料名称就不写具体材质。
私人改装或二手转售，不自动升级为开发商统一精装交付标准；仍可按明确事实记录并说明来源性质。
正例（独立合成）：原文“那张餐桌想走中古风，房子还没装好”，
可写“餐桌计划采用中古风格，住宅装修尚未完成”，不写“全屋已完成中古精装”。
短评论“比这小的也听得到”无法唯一确认比较对象时，保留相对说法，不补小楼盘或具体机型。
清楚的对象、数量、尺寸仍须保留，不因局部转录噪声清空整条记录。'''
INSTRUCTION+='''
“放好了/放在那里”只证明位置或摆放，不能自动升级“已安装完成”。
某家具附近的“装了一半”指代不清时，不改成“住宅装修半完成”；明确全屋装修进度才可写全屋。
窗户较大是尺度描述，不得用安装状态替换而遗漏大小。来源为口播但发言者身份未核实，不写业主或开发商称。
'''


def guessed_asr_reason(reason):
    return bool(re.search(r'疑为.{0,25}(?:语音|识别|ASR)|疑似.{0,15}(?:识别错误|ASR)|'
                          r'(?:ASR|语音识别).{0,15}错误.{0,25}(?:指|还原|纠正)',str(reason or ''),re.I))


def issues(source, prose):
    source=str(source or '');prose=str(prose or '');out=[]
    if (re.search(r'窗户?.{0,8}放好了',source) and not re.search(r'窗户?.{0,10}(?:已安装|安装完成|装好了)|(?:已安装|安装完成).{0,10}窗',source)
            and re.search(r'(?:窗户?.{0,10}(?:已安装|安装完毕|安装完成)|(?:已安装|安装完毕|安装完成).{0,10}窗)',prose)):
        out.append({'accepted':False,'reason':'原文窗户仅称放好，不能写成已安装完成；保留明确尺度等事实而不猜安装状态'})
    half_furniture=re.search(r'(?:桌子|柜子|餐桌|衣柜|沙发)[^。；]{0,35}装了一半',source)
    explicit_whole_half=re.search(r'(?:全屋|整屋|整个房子|住宅装修|房子装修)[^。；]{0,15}(?:装了一半|半完成|只完成一半)',source)
    if (half_furniture and not explicit_whole_half and re.search(r'(?:全屋|住宅|房屋|整屋).{0,12}(?:半完成|一半|未完成)',prose)):
        out.append({'accepted':False,'reason':'原文家具附近的半完成指代不清，文案扩大为整屋装修进度；须省略不明范围并保留明确配置'})
    if (re.search(r'厨房[^。；]{0,15}窗[^。；]{0,10}(?:很大|较大|很宽|宽大)',source)
            and bool(prose.strip())
            and not re.search(r'厨房[^。；]{0,15}窗[^。；]{0,10}(?:大|宽)|厨房[^。；]{0,10}(?:较大|很大|大|宽)[^。；]{0,8}窗|(?:较大|大尺寸|宽大)[^。；]{0,8}厨房[^。；]{0,8}窗',prose)):
        out.append({'accepted':False,'reason':'原文明示厨房窗户较大，文案遗漏厨房对象或主要尺度属性；须保留对象及尺度，不用其他窗户状态替代'})
    whole_source=re.search(r'全屋|整屋|全房|所有房间|整个房子|房子.{0,6}(?:整体|全部)',source)
    if (re.search(r'桌子|柜子|餐桌|衣柜|沙发',source) and not whole_source
            and re.search(r'全屋[^。；]{0,12}(?:风格|法式|中古|中式|装修)|(?:原计划|计划|采用|进行).{0,8}(?:法式|中古|中式)装修',prose)):
        out.append({'accepted':False,'reason':'原文提及家具但没有全屋范围依据，转写扩成全屋风格；须重新核明确对象，不借常识扩大范围'})
    for obj in ('过滤窗','窗户','新风','中央空调','橱柜','地板','电梯'):
        unfinished=re.search(re.escape(obj)+r'.{0,3}(?:装不完|未安装|没安装|安装未完成)',source)
        completed=re.search(r'(?:已|已经)(?:全部)?安装[^。；]{0,18}'+re.escape(obj)
                            +'|'+re.escape(obj)+r'.{0,5}(?:已安装|已经安装|已完成)',prose)
        if unfinished and completed:
            out.append({'accepted':False,'reason':f'原文{obj}安装未完成，但转写写成已安装；必须保留对应对象的未完成状态'})
    # This narrow observed noise alarm does not reject clean bamboo wording.
    # It requests review, never assigns a replacement material or removes the
    # separately clear environmental-material fact.
    if (source.count('竹竹')>=2 and not re.search(r'竹材|竹质|竹板|竹地板|竹木|竹子',source)
            and re.search(r'(?:使用|采用|运用|用)[^。；]{0,15}(?:竹材|竹质|竹板|竹地板|竹木)',prose)):
        out.append({'accepted':False,'reason':'原文材料名只有重复转录音节，转写却确定为竹材；明确环保材料事实仍可保留，具体材质需审核'})
    return out
