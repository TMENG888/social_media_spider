"""Independent counterexample-oriented comment prose audit; not a slicing stage."""
import prose_audit_references as references

SYSTEM = '''只输出JSON。你是独立反向挑错者，找当前评论摘要最可能错误的对象、关系和态度，不默认摘要正确。
source_text是全部当前评论，不使用父文章补事实。逐个prose_catalog的prose_key恰好检查一次。
每项可能有多个命题；任一命题错误就unsupported，不能因为其他半句正确就通过。
逐项核对：
1 对象：项目、地块、房间、发言者。最近出现的项目名不自动成为后一句“北侧/那边”的对象。只有明确的原文承接链可消歧；链不唯一则uncertain，不任选项目。
2 关系：两个并列抱怨不证明因果；“A不错，但B更好”与“二选一也许A稍好”不是同样的接受程度。
3 模态：可能、估计、没听过、询问、建议、相对比较不能升格为实测、接受、确认或绝对满意。
4 限定：室内/室外、低频/持续、有限影响/严重影响不能混在一起。说明影响程度的限定属于同一个命题。
5 核心内容：不能只总结附和而丢具体事件；不用穷举次要附和，但应保留主要不同声音。
异于测试样本的反例：甲区临环路很吵，另一人称乙北地块可能较好，回复“最北侧也没用”不能仅靠最近名字改成乙区噪音严重。
“没坐过，如果巴士和轮渡二选一也许巴士好一点”不支持“乘客觉得巴士尚可”，只支持未实测的相对偏好。
“街上很吵。另一人说排队堵路”不能概括成排队使街上更吵。只有无人机[视频]不能称噪音视频。
每项source_keys选择程序提供的实际原文键，不能用子评论号代替。
返回：{"checks":[{"prose_key":"实际键","status":"supported/unsupported/uncertain",
"source_keys":["实际原文键"],"object_binding_supported":true,"relation_supported":true,
"modality_preserved":true,"qualifiers_preserved":true,"why":"具体对象承接、关系与限定的支持依据或错误",
"confidence":0.95}],"coverage":{"captures_primary_points":true,"source_keys":["实际原文键"],
"why":"保留的主要事实或实际遗漏","confidence":0.95}}。
四个布尔项必须逐项给出；不确定时false且status=uncertain。why简短，不输出分析过程。不能改写摘要。
'''


def payload(source, prose):
    return references.payload(source, prose, '')


def verify(source, prose, response):
    okay, audit = references.verify(source, prose, response)
    checks = response.get('checks') if isinstance(response, dict) else None
    if not isinstance(checks, list):
        return False, audit
    for check in checks:
        if not isinstance(check, dict):
            continue
        missing = [key for key in ('object_binding_supported', 'relation_supported',
                    'modality_preserved', 'qualifiers_preserved') if check.get(key) is not True]
        if missing:
            okay = False
            audit.append({'accepted': False, 'reason': '评论反向核验未通过：'+','.join(missing),
                          'prose_key': check.get('prose_key'), 'why': check.get('why')})
    return okay, audit
