"""Short literal anchors and physical-object boundaries; never repair source text."""
import copy
import delivery_v66 as current

VERSION = 'delivery-v11.67-short-literal-object-boundaries-20261010'
pipeline = current.pipeline

POSITION_NOTE = '''
定位协议：start_phrase仅用于标出起点，不是摘要也不是整片摘录。最多24个字符，
必须是所选start_source_key条目text内部的连续逐字原文，不能跨越目录条目。
若起点在条目开头必须用null；在条目内部则用起点开始的4至24字即可。
先独立决定语义边界，再查目录选择所属条目，不得为适应目录而移动边界。
编辑标题“第六维度：园林与会所”不能把两个独立物理设施强行合片。
例如原文按甲园林、甲会所、乙园林、乙会所介绍，应保留这些连续对象转换，
而不是把整段统称“园林会所比较”，也不能跨过甲会所拼接两段园林。
同一个完整厨房系统的风压、止逆阀、接口密封仍放一片，不按零件切分。
问答内部若从卫生间防臭纠正转到厨房接口密封，要按实际对象转场判断；
不能因统一问答标题就当一个对象，也不能把紧接的施工纠正误放进结尾邀约。
结尾邀约片只从实际邀约文字开始，前面的有意义施工事实不能随邀约排除。
所有判断只来自全文，不预设片数，不复制证据行，不根据标签多少决定边界。
'''


def boundary_call(system, payload, schema, doc, phase, runner):
    contract = copy.deepcopy(schema)
    contract['properties']['units']['items']['properties']['start_phrase']['maxLength'] = 24
    return current.boundary_call(system + POSITION_NOTE, payload, contract, doc,
                                 phase.replace('v11.65', 'v11.67'), runner)


def activate():
    current.activate()
    current.current.boundaries.bounded = boundary_call
    pipeline.previous.VERSION = VERSION
    pipeline.previous.IMPLEMENTATION_FILES = list(dict.fromkeys(
        pipeline.previous.IMPLEMENTATION_FILES + ['delivery_v67.py']))


if __name__ == '__main__':
    activate()
    pipeline.previous.main()
