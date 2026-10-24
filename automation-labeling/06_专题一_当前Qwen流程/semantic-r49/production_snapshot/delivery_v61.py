"""Operational meanings for semantic predicates and compact full definitions."""
import delivery_v60 as current
import label_selection_candidates_v61 as candidates

VERSION = 'delivery-v11.61-operational-predicates-compact-full-dictionary-20261010'
_materialize = current.integrated.selection.materialize


def materialize(text, index, raw):
    # Keep raw replies untouched in the structural audit. Normalize repeated
    # same-ID proposals only, then independently bind every proposed label.
    return _materialize(text, index, candidates.canonicalize(raw))


def activate():
    current.activate()
    pipeline = current.integrated
    pipeline.selection.payload = candidates.payload
    pipeline.selection.materialize = materialize
    pipeline.selection.SYSTEM += '''
这不是单选分类。同一原文事实可满足不同对象/属性的多个定义，不能因为已选一个标签就跳过其余。
完整path限定对象，emphasis说明强调方向，definition是具体条件；每条都核，不因词面最突出就只选最显眼一个。
同ID多个有据事实可合并source_keys/object_keys及why，不按事实重复输出同一ID。'''
    pipeline.prose.GENERATE += '''
产品做法优先用“设置/采用/配置/规定”等措施句式独立组织；只保留清楚的对象、措施、尺寸和状态。
删掉“全方位解决”“彻底杜绝”等保证性宣传，不把措施用途升级为已经实测的效果。
规范或建议应写“应/建议”，不能当已安装事实。人物昵称和节目口头互动不用搬入产品做法。
评论摘要优先主要事实与重要限定，昵称可省略以保留不同说话者的观点。项目不明不妨碍概括明确态度。
confidence只评价当前文案对原文的忠实度，不表示项目ID或发布者职业是否确定；没有案名不等于清楚的短评价无法概括。
合成例：主评说A布局好，回复说A客厅拥挤，应写“主评认可A布局，回复者认为其客厅拥挤”，不能只写一方。
合成例：社区西侧早高峰车流较多，摘要不能变成整个社区一直拥堵。'''
    pipeline.prose.VERIFY += '''
明确字段含义：rewritten判断输入prose是否已经独立转写，不是问你本次是否重写。
若待核产品句式已重新组织且保持对象与事实，rewritten=true；保留必要名词、数值、单位不算照搬。
不要因为你的任务“不重写”就机械填rewritten=false。
faithful核每个断言与原文，core_covered核主要事实和改变含义的场景/范围，不是只核是否涉及相同话题。
“A西侧与B北侧相近”不可概括“A与B整体相近”，会扩大事实适用范围，faithful=false。
纯摘要省略昵称允许，但两人实质不同的意见不可只留一方。'''
    pipeline.prose.coverage.SYSTEM += '''
两名发言者实质相反或不同的评价都是major；不能为迁就既有摘要把被反驳的主评降为minor。
有范围、场景、频率或时段限定时，summary_covers只有这些改变含义的限定未被扩大才为true。
读source_text和summary的实际表述，不仅判断是否出现同一主题词。'''
    pipeline.identity.SYSTEM += '''
supported只判断案名及指代关系是否有原文支持，不判断是否存在候选ID。
候选外的明确案名也可supported=true，程序会保留名称并让ID为空；不得因找不到候选ID而把明确点名说成不支持。
候选全称没在评论中逐字出现、仅有未登记简称时，不可用direct套候选全称；有父文唯一关系则parent_relation，否则保留实际简称或不确定。
严禁用常识把地块名称映射到本字典没有登记的另一个住宅案名，父文也未点名时不可编造关系。'''
    pipeline.previous.VERSION = VERSION
    pipeline.previous.IMPLEMENTATION_FILES = list(dict.fromkeys(pipeline.previous.IMPLEMENTATION_FILES +
        ['delivery_v61.py', 'label_selection_candidates_v61.py']))


if __name__ == '__main__':
    activate()
    current.integrated.previous.main()
