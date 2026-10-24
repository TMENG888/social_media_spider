import sys,json
from pathlib import Path
sys.dont_write_bytecode=True;R=Path(__file__).parent;sys.path.insert(0,str(R/'production_snapshot'))
import delivery_v4 as api
sys.stdout.reconfigure(encoding='utf8')
docs=json.loads((R/'inputs/A_documents.json').read_text(encoding='utf8'))
runner=api.ApiRunner(R/'api_cache',concurrency=1)
system='''你是住宅产品文章的语义分段器。只做分段，不做标签、摘要、身份判断。
全文按住宅空间/产品主题的转换分段。例如原文“绿地率30%。立面用陶板。A户型主卧有衣帽间。会所有泳池。”应4段，而非一整段。规划指标可合一段；同一空间相关指标不拆。
独立的景观、会所、整套户型、客餐厅、主卧、次卧等若各有完整做法则分段。开场、周边和广告结尾也需处理，可单独成段。
仅返回JSON {"cuts":[{"quote":"每段开头连续8至16字的原文，不是整段","occurrence":1,"theme":"本段主题"}]}。
第一段从全文第一个字开始，不丢任何文字。切点按原文顺序排列。occurrence是短quote在全文第几次出现，绝不是段落序号。'''
for d in docs[:2]:
 x,m=runner.call(system,{'text':d['text']},d,'专题一纯语义切点试验');print(json.dumps({'id':d['source_id'],'response':x,'status':m['status']},ensure_ascii=False))
