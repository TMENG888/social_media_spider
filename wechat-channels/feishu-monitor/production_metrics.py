"""Verified post-commit telemetry, separate from logs, leases and collection dates."""
from datetime import datetime, timezone, timedelta
import json
from worker_visibility import reportable_worker

def stamp(value):
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)
    except (ValueError,AttributeError):return None

def hourly_metrics(events,now,generation):
    counts=dict(newVideos=0,metadataUpdates=0,subtitleWrites=0,manuallyApprovedSubtitleWrites=0,newComments=0,commentUpdates=0)
    seen=set();accepted=0
    for event in events:
        dt=stamp(event.get('committedAt'))
        if not dt or not event.get('readbackVerified') or event.get('generation')!=generation or not event.get('eventId'):continue
        if event['eventId'] in seen:continue
        seen.add(event['eventId'])
        if not now-timedelta(hours=1)<=dt<=now:continue
        accepted+=1
        for item in event.get('items',[]):
            if item.get('platform')!='微信视频号':continue
            kinds=item.get('types',[])
            if item.get('table')=='ods_social_media_post':
                if item.get('operation')=='insert':counts['newVideos']+=1
                elif 'metadata' in kinds:counts['metadataUpdates']+=1
                if 'subtitle' in kinds:
                    counts['subtitleWrites']+=1
                    if item.get('subtitleApproval')=='manual_approval':counts['manuallyApprovedSubtitleWrites']+=1
            elif item.get('table')=='ods_social_media_comment' and 'comment' in kinds:
                counts['newComments' if item.get('operation')=='insert' else 'commentUpdates']+=1
    return {'windowStart':(now-timedelta(hours=1)).isoformat(),'windowEnd':now.isoformat(),'verifiedBatches':accepted,**counts,'qualifiedSubtitleWrites':None,'averageVideoCollectionSeconds':None,'note':'Only deployed verified telemetry, not historical backfill; subtitle writes are not independent quality audit.'}

def read_outputs(c,prefix,generation,now):
    key=prefix+':production-output'
    if c.command('TYPE',key)!='stream':return {'available':False,'hourly':None,'latest':[],'reason':'production_telemetry_not_observed'}
    # Stream IDs are receive times; late uploads are filtered using committedAt.
    start=str(int((now-timedelta(hours=1)).timestamp()*1000))+'-0'
    events=[];cursor=start;truncated=False
    for _ in range(20):
        page=c.command('XRANGE',key,cursor,'+','COUNT',500)
        if not page:break
        for mid,values in page:
            fields=dict(zip(values[::2],values[1::2]))
            try:events.append(json.loads(fields.get('record','{}')))
            except ValueError:pass
        cursor='('+page[-1][0]
        if len(page)<500:break
    else:truncated=True
    latest=[]
    raw=c.command('HGETALL',prefix+':production-output-latest')
    for value in raw[1::2]:
        try:r=json.loads(value)
        except ValueError:continue
        if r.get('generation')==generation and reportable_worker(r.get('worker')):latest.append(r)
    identities={(e.get('computer'),e.get('worker')) for e in events if e.get('generation')==generation and e.get('readbackVerified') and reportable_worker(e.get('worker'))}
    per_worker=[{'computer':computer,'worker':worker,**hourly_metrics([e for e in events if (e.get('computer'),e.get('worker'))==(computer,worker)],now,generation)} for computer,worker in sorted(identities,key=str)]
    return {'available':True,'hourly':hourly_metrics(events,now,generation),'perWorker':per_worker,'latest':latest,'truncated':truncated,'clockCaveat':'Cross-machine commit clocks require time synchronization; future-dated events are excluded.'}
