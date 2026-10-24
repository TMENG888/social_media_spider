"""Do not convert a contaminated two-name heading into shared project facts.

No name is chosen or removed automatically. A generated joint assertion is
sent back for a neutral rewrite or manual review with the original preserved.
"""
import re


def issues(source,prose):
    source=str(source or '');prose=str(prose or '');out=[]
    for match in re.finditer(r'([\u4e00-\u9fff]{2,20})\s*[•丨]\s*([\u4e00-\u9fff]{2,20})\s*[:：]',source):
        left,right=match.groups()
        if left==right or left not in prose or right not in prose:continue
        joint=re.search(re.escape(left)+r'\s*(?:与|和|及|[•丨])\s*'+re.escape(right),prose)
        # An explicit comparison does not say both projects share a configuration.
        if joint and not re.search(r'对比|比较|分别|差异|不同|原文标题|标题残留',prose):
            out.append('连续双名称标题不能直接转为两项目共同配置：'+left+' / '+right+'；对象未唯一核实时用泛指概括并说明归属待核')
    return out
