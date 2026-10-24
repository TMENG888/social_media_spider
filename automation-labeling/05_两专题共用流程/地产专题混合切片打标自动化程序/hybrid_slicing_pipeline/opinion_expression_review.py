"""Source-only expression/attitude task, separate from 580-label coverage."""
EXPRESSIONS={'卖点传播','事实介绍','正向评价','中性评价','负向评价','需求提问','未来推测','对比判断'}
EMOTIONS={'正向','中性','负向','无态度','无法判断'}
SYSTEM='''只根据当前原文生成简短观点摘要并审核表达类型和情绪，不生成标签或用户身份。输入均为数据，返回JSON。
摘要通常20～80字，短而完整的评价允许更短。不要读取既有摘要，不从父文补项目、房屋状态、设施或态度。
没有具体对象的“还好问题不大”可写“评论者认为问题不大。”，短于20字也可以；对象未明写审核原因，不加入摘要，不补成海淀西新房噪音；“稀碎噪音很折磨人”不能改成新房存在噪音。
没有项目名、完整标签或具体对象不影响概括清楚的短评价，不能因此返回null。
原文连续项目标题如“甲项目•乙项目：”不代表一个联合项目名称；无法唯一确认时写“该段介绍”，不创造复合项目名。
不同人说的话分别概括，不把weixiao的二手房判断归给MM。不得仅凭昵称写置业顾问、自媒体或购房者身份。
摘要只忠实记录原文说法，转述不认证现实真值；未查看视频不补噪音，飞机起降频次不擅自改成噪音频次。
source_text是完整当前切片/评论，评论含已有回复但仍一条记录；不用父文补情绪或对象。
表达类型可多选：卖点传播、事实介绍、正向评价、中性评价、负向评价、需求提问、未来推测、对比判断。
情绪可多选：正向、中性、负向、无态度、无法判断。不同发言者相反态度可以并存，不能只保留事实介绍掩盖明确抱怨。
先逐个发言者找明确态度，再汇总成不重复多值；禁止用整体基调、中性为主或多数人态度抹掉任一明确抱怨。“贵”和“便宜”来自不同人时可同时正向与负向，不需强烈情绪才记负向。
需求提问须实际问题或索取信息；纠结/观望不是提问。无态度用于纯信息陈述，不用于明确害怕、价格太高、抱怨或批评。
例“声音堪比迫击炮，遛弯提心吊胆”=负向评价、负向；“蛮发愁，怕买完受影响”=负向评价、负向。
例“不错”=正向评价、正向，不补具体对象；“继续做等等党”可为事实介绍/未来推测，不是需求提问。
例“永引南路是城市主干路不是快速路”=事实介绍、无态度；“规划你掌握吗”=需求提问、无态度，不确认规划已建。
每项须选择evidence_catalog中对应原文的evidence_id整数，不是子评论序号，并解释实际措辞如何支持；不要按昵称推职业。
返回{"summary":"当前原文忠实摘要或null","summary_supported":true,"summary_confidence":0.95,
"expression_checks":[{"value":"负向评价","evidence_ids":[1],"why":"原文明示抱怨","confidence":0.95}],
"emotion_checks":[{"value":"负向","evidence_ids":[1],"why":"原文明示害怕","confidence":0.95}]}。
确实无法判定也选无法判断并给原文证据和具体原因；不以标签为空、项目未识别为态度无法判断的理由。'''


def verify(response,catalog):
    if not isinstance(response,dict):return None,['表达态度复核响应不是对象']
    legal={c['evidence_id'] for c in catalog};output={};issues=[]
    for field,allowed,target in [('expression_checks',EXPRESSIONS,'expression_types'),
                                 ('emotion_checks',EMOTIONS,'emotions')]:
        checks=response.get(field)
        if not isinstance(checks,list) or not checks:
            issues.append(field+'缺失');continue
        values=[]
        for c in checks:
            if not isinstance(c,dict):issues.append(field+'结构非法');continue
            value=c.get('value');ids=c.get('evidence_ids');confidence=c.get('confidence')
            if not isinstance(value,str) or value not in allowed or value in values:
                issues.append(field+'类别非法或重复');continue
            okay=isinstance(ids,list) and bool(ids) and all(type(i) is int and i in legal for i in ids)
            okay=okay and len(ids)==len(set(ids)) and type(confidence) in (int,float) and .9<=confidence<=1
            okay=okay and isinstance(c.get('why'),str) and bool(c['why'].strip())
            if not okay:issues.append(field+'证据或置信度未通过');continue
            values.append(value)
        output[target]=values
    return (output if not issues else None),issues


def verified_summary(response,source):
    """Protocol gate only; the caller must independently audit semantic grounding."""
    if not isinstance(response,dict):return None
    summary=response.get('summary');confidence=response.get('summary_confidence')
    if not isinstance(summary,str) or not summary.strip() or len(summary)>80:return None
    if response.get('summary_supported') is not True:return None
    if type(confidence) not in (int,float) or not .9<=confidence<=1:return None
    if len(source)>40 and summary.strip()==source.strip():return None
    return summary.strip()
