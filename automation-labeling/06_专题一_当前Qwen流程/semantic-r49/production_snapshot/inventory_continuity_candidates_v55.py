"""Staged model-led fact-restatement ranges, independently approved or retained.

Only model-declared literal source-key relations propose ranges. No keyword,
tag, length or shared project directly sets a physical boundary. Intervening
members stay in every review; a different system means rejection, not skipping.
"""
import copy
import final_range_group_protocol_v50 as ranges
import final_boundary_closure_v47 as closing
import source_only_group_recovery_v50 as recovery
import shared_mechanism_protocol_v58 as mechanism_proof

def candidates(ledger,entries):
    members=(ledger or {}).get('members',{});positions={e['source_unit_key']:i for i,e in enumerate(entries)}
    proposed=set()
    for key,record in members.items():
        if key not in positions or record.get('relation') not in {'restatement','correction'}:continue
        score=record.get('confidence')
        if type(score) not in (int,float) or not .9<=score<=1:continue
        for earlier in record.get('related_source_keys',[]):
            if earlier in positions and positions[earlier]<positions[key]:proposed.add((positions[earlier],positions[key]))
    return sorted(proposed,key=lambda span:(span[1]-span[0],span))

def review(doc,original,segments,entries,ledger,baseline,runner):
    positions={e['source_unit_key']:i for i,e in enumerate(entries)}
    raw=baseline.get('post_split_raw_group_protocol')
    if not isinstance(raw,dict):return baseline,[],[],['未取得实际原键分区，未静默修复']
    groups=copy.deepcopy(raw['groups']);audit=[];calls=[]
    for a,b in candidates(ledger,entries):
        touching=[i for i,g in enumerate(groups) if positions[g['start_key']]<=b and positions[g['end_key']]>=a]
        if len(touching)<2:continue
        x,y=touching[0],touching[-1]
        # Expand only through already independently approved whole groups;
        # the newly expanded complete span is independently reviewed afresh.
        a=positions[groups[x]['start_key']];b=positions[groups[y]['end_key']]
        validator=recovery.partition_validator(doc,original,segments,entries,a,b,ranges.apply)
        checked,records,used,issues=mechanism_proof.review(doc,entries,a,b,runner,validator)
        calls+=used;audit.append({'proposed_range':[a,b],'checks':records,'issues':issues})
        if checked:
            groups[x:y+1]=[dict(checked,start_key=entries[a]['source_unit_key'],end_key=entries[b]['source_unit_key'])]
    out,issues=ranges.apply(doc,original,segments,{'groups':groups})
    if issues:return baseline,audit,calls,issues
    out['inventory_continuity_candidate_audit']=audit
    return out,audit,calls,[]
