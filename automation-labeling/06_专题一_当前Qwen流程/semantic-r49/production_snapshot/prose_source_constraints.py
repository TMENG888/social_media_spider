"""Narrow source-only inference alarms, never source slicing or tag selection."""
import re
import asr_scope_fidelity


def issues(source, prose):
    source = re.sub(r'【(?:父评论|子评论\d*)｜[^】]*】', '', str(source or ''))
    prose = str(prose or '')
    out = []
    previous_interview=r'(?:之前|此前|早前)[^。；]{0,35}(?:采访|受访)[^。；]{0,45}(?:整改|维修)'
    explicit_current=r'(?:目前|现在|现已)[^。；]{0,18}(?:完成整改|已整改|完成维修|已维修)'
    if (re.search(previous_interview,source) and re.search(r'整改|维修',prose)
            and not re.search(r'此前|之前|先前|早前|曾',prose)
            and not re.search(explicit_current,source)):
        out.append({'reason':'原文整改/维修是此前受访时的声称，转写未保留此前/曾的时间限定，不能写成当前已落实的事实',
                    'accepted':False})
    if ('[视频]' in source or '【视频】' in source) and not re.search(r'声|音|吵|响|听|聋|扰', source):
        if re.search(r'噪音|噪声|声响|轰鸣|声音|吵闹', prose):
            out.append({'reason': '原文只有视频标记且没有声音文字证据，摘要新增听觉或噪音判断', 'accepted': False})
    cause = r'(?:堵车|拥堵|路堵)[^。；，]{0,15}(?:导致|使得|加剧|增加|更大|更甚|更吵)'
    if re.search(cause, prose) and not re.search(cause, source):
        out.append({'reason': '摘要把堵车与噪音写成增强或因果关系，但原文未明示该关系', 'accepted': False})
    if (re.search(r'没(?:有)?(?:听|去|坐|用|体验|看)过', source)
            and re.search(r'二选一|好一点|相比|相对', source)
            and re.search(r'尚可|可以接受|能接受|很满意', prose)
            and not re.search(r'尚可|可以接受|能接受|很满意', source)):
        out.append({'reason': '原文未体验且只作相对选择，摘要新增尚可、接受或满意的绝对态度', 'accepted': False})
    return out+asr_scope_fidelity.issues(source,prose)
