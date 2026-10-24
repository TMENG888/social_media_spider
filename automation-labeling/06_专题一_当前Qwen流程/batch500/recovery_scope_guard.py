"""Qwen adjudicates scope conflicts in failed sources only, before rescue.

No reference answers, hardcoded source IDs or automatic keyword exclusions.
This wrapper does not modify the frozen semantic pipeline or successful caches.
"""
import copy
SYSTEM='''仅裁决专题一范围冲突，不重做标签或摘要。此前本片范围判断为不交付，但标签复核又提出标签，二者冲突。
专题一对象是住宅项目自身的产品做法，包括项目明确自建或自带的社区商业及公共空间；独立商场、外部城市配套、酒店、办公商业本身不因此变成住宅产品。集团旗下不等于住宅自身配置。用全文辨认对象和关系，用unit_text确认本片产品对象。不把标签存在当作范围已正确的证明。
明确为住宅自身或已证明住宅自建/自带的配置，residential_owned=true且给出全文逐字证据；若是独立商业或关系未被证明，false，并说明实际对象及为何不属于住宅自身。不得仅因未出现住宅两个字便排除；读完全文再判断。只输出JSON residential_owned, reason, evidence_quotes。'''

def install(batch):
    original=batch.pipeline.label_units_exhaustive
    def guarded(doc,units,tax,runner):
        before,audit=original(doc,units,tax,runner)
        decisions=[]
        for u in units:
            if u['deliver'] or not u['labels']:continue
            schema=batch.pipeline.obj({'residential_owned':{'type':'boolean'},'reason':{'type':'string','minLength':1},'evidence_quotes':batch.pipeline.arr({'type':'string','minLength':1})})
            payload={'source_title':doc['title'],'source_text':doc['text'],'unit_text':u['text'],'prior_scope_reason':u.get('reason'),'candidate_labels':copy.deepcopy(u['labels'])}
            verdict,metrics=runner.call(SYSTEM,payload,doc,'专题一失败来源范围冲突独立裁决',response_schema=schema)
            if metrics['status']!='success':raise ValueError('范围冲突独立裁决请求失败')
            assert type(verdict.get('residential_owned'))==bool and verdict.get('reason')
            quotes=verdict.get('evidence_quotes');assert isinstance(quotes,list)
            assert all(isinstance(q,str) and q and q in doc['text'] for q in quotes)
            if verdict['residential_owned']:assert quotes,'住宅自身归属必须提供原文证据'
            decision={'index':u['index'],'start':u['start'],'end':u['end'],'verdict':verdict,'original_labels':copy.deepcopy(u['labels']),'engine':'Qwen independent residential ownership scope adjudication'}
            decisions.append(decision)
            u['scope_conflict_adjudication']=decision
            if not verdict['residential_owned']:
                u['labels']=[]
                u['reason']='范围冲突独立裁决：'+verdict['reason']
        audit['scope_conflict_adjudications']=decisions
        batch.save(batch.ROOT/'scope_recovery'/f'{doc["record_id"]}.json',{'record_id':doc['record_id'],'decisions':decisions})
        return before,audit
    batch.pipeline.label_units_exhaustive=guarded
