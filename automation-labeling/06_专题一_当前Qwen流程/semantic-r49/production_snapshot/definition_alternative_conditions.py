"""Staged dictionary-added-condition leads. Re-review only, never assign tags."""
import re


def instruction_parts(tag):
    text=str(tag.get('instruction') or '') if isinstance(tag,dict) else str(tag or '')
    pieces=re.split(r'例\s*[：:]|例如\s*[：:]?',text,maxsplit=1)
    return pieces[0],pieces[1] if len(pieces)>1 else ''


def review_reasons(reason, tag):
    reason=str(reason or '');mandatory,example=instruction_parts(tag);out=[]
    mandatory_brand=bool(re.search(r'(?:必须|须明确|仅记录|要求提供)[^。；]{0,18}(?:品牌|型号)',mandatory))
    optional_configuration=bool(re.search(r'(?:品牌|型号|规格)[^。；]{0,25}或(?:具体)?配置',example))
    missing_brand=bool(re.search(r'(?:未提供|未提及|缺乏|缺少|没有|无明确)[^。；]{0,35}(?:品牌|型号)',reason))
    # "No air conditioner brand/model/configuration is mentioned" is a
    # legitimate absence, not proof that the reviewer required a brand.
    acknowledged_description=bool(re.search(
        r'(?:原文|内容|本段|切片)(?:仅|只|虽|虽然)?(?:已|明确)?(?:提及|提到|描述|提供|涉及|回答|包含)|'
        r'(?:仅|只)(?:描述|提及|提供|包含)',reason))
    if optional_configuration and missing_brand and not mandatory_brand and acknowledged_description:
        out.append('字典示例接受品牌、型号、规格或配置；拒绝理由疑似把可选品牌型号升级为必需条件，须重核原文配置和对象')
    requires_real_delivery=bool(re.search(r'(?:仅记录|必须|限于|只接受)[^。；]{0,18}(?:实际交付|已经施工|已施工|已建成)',mandatory))
    unproven_implementation=bool(re.search(
        r'(?:未|缺乏|无法)[^。；]{0,45}(?:本项目|实际|实际工程)[^。；]{0,25}(?:采用|施工|关联|落实)',reason))
    if unproven_implementation and not requires_real_delivery and re.search(r'做法|配置|施工|工艺',mandatory):
        out.append('字典未限定实际落地；拒绝理由疑似排除了有原文声称的规划或工法讲解，须重核来源性质与具体做法')
    if example and re.search(r'通常不归类|(?:定义)?示例(?:为|是)[^。]{0,90}(?:未提及|不包含|没有)|(?:示例|例子)[^。]{0,55}(?:仅限|只限|限定为)',reason):
        out.append('拒绝理由疑似用行业分类或示例限定替代字典正文；须重核明确对象及事实，示例不自动穷尽允许配置，也不能据此自动补标')
    return out


INSTRUCTION='''
精读标签对象路径及实际打标说明，把真正要求和“例”分开，不修改字典。
“品牌、型号、规格或配置”中的或是备选条件，不是必须同时具备品牌型号。
原文明示干区地漏自动补水、共用存水弯、水封大于50毫米，是可核的配置/规格信息，
不能只因没有品牌型号就否认这些信息；但仍须原文明确属于相应部位，不能用常识猜卫生间。
工法样板或问答中明确要求接口如何使用专用耐高温胶密封，是作者声称的工法，
如字典没有只收已交付的限定，不要求额外证明现实实际施工。记录声称/样板/规划性质，不能转写为已完成。
反例：仅说材料名称不证明施工方式，仅说技术很好不支持具体配置；
若定义明确要求品牌、实际交付或具体数值，则严格遵从，不能因这段提示自动批准。
此次是定义重核，不是自动给标签；对象、属性、逐字证据及来源性质均不符仍拒绝。
不能只因原文配置不同于示例就否定上位定义，不将“例”默认为穷尽清单。
如行业分类使某配置与上位定义存在争议，明确标ambiguous和具体争议，不靠“通常”补出字典没有的排除条件。
'''
