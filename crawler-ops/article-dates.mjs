// Read-only local checkpoint inspection, executed on the collecting computer.
import fs from 'node:fs';
import path from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';

export const COLLECTION_PASS='articles-comments-20261110-v1';

export function publicationDate(value) {
  if(value==null)return null;
  const text=String(value).trim();
  const m=/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(text);
  if(!m)return null;
  const [year,month,day]=m.slice(1,4).map(Number);
  const d=new Date(Date.UTC(year,month-1,day));
  if(year<1900||year>2100||d.getUTCFullYear()!==year||d.getUTCMonth()!==month-1||d.getUTCDate()!==day)return null;
  if(m[4]&&(Number(m[4])>23||Number(m[5])>59||Number(m[6]||0)>59))return null;
  if(m[4]&&/(?:Z|[+-]\d\d:\d\d)$/.test(text)){
    const at=new Date(text);if(!Number.isFinite(at.getTime()))return null;
    return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'medium',hourCycle:'h23'}).format(at);
  }
  return m[0].replace('T',' ');
}

export function readCheckpointDates(checkpoint,keyword,platform,projects) {
  const db=new DatabaseSync(checkpoint,{readOnly:true});
  try{
    db.exec('PRAGMA query_only=ON; PRAGMA busy_timeout=750;');
    const rows=db.prepare(`SELECT note_id,
      json_extract(result_json,'$.post."文章id"') AS articleId,
      json_extract(result_json,'$.post."文章时间地点"') AS publishedAt,
      json_extract(result_json,'$.post."文章获取时间"') AS capturedAt,
      json_extract(result_json,'$.post."项目"') AS project,
      json_extract(result_json,'$.post."平台"') AS platform
      FROM candidate WHERE keyword=? AND status='completed' AND json_valid(result_json)
      AND json_type(result_json,'$.post')='object' LIMIT 10001`).all(keyword);
    if(rows.length>10000)throw new Error('DATE_SCAN_LIMIT');
    const valid=rows.filter(r=>r.platform===platform&&projects.includes(r.project)&&r.articleId);
    const captured=valid.map(r=>({...r,capturedAt:publicationDate(r.capturedAt)})).filter(r=>r.capturedAt);
    captured.sort((a,b)=>b.capturedAt.localeCompare(a.capturedAt)||String(a.articleId).localeCompare(String(b.articleId)));
    return {source:valid.length?'ok':'empty',latestCollectedPublishedAt:publicationDate(captured[0]?.publishedAt),
      latestCollectedAt:captured[0]?.capturedAt||null,
      _postIds:[...new Set(valid.map(r=>String(r.articleId)))],localPosts:valid.length};
  }finally{db.close();}
}

export function readMachineDates(requests,packageRoot) {
  return requests.map(r=>{
    const result={platform:r.platform,keyword:r.keyword,taskId:r.taskId,collectionPass:r.collectionPass,source:'unavailable'};
    try{
      if(!['xhs','douyin'].includes(r.platform)||!/^worker-\d{2}$/.test(r.worker)||!r.keyword||r.platform==='xhs'&&(!r.campaign||/[\\/]|\.\./.test(r.campaign)))throw new Error('DATE_TARGET_INVALID');
      const platform=r.platform==='xhs'?'小红书':'抖音';
      const root=path.resolve(packageRoot,platform,r.worker);
      if(r.collectionPass!==COLLECTION_PASS||r.collectComments!==true||!new RegExp('^'+(r.platform==='xhs'?'xhs':'dy')+'-[a-f0-9]{64}$').test(r.taskId||''))throw new Error('DATE_BATCH_INVALID');
      const manifest=JSON.parse(fs.readFileSync(path.join(packageRoot,platform,'common','tasks','redis-tasks.json'),'utf8').replace(/^\uFEFF/,''));
      const task=manifest.tasks.find(t=>t.redisTaskId===r.taskId&&t.keyword===r.keyword&&t.topic==='专题一'&&t.collectComments===true&&t.collectionPass===r.collectionPass);
      if(!task)throw new Error('DATE_BATCH_MISMATCH');
      const slug=String(r.keyword).normalize('NFKC').replace(/[\\/:*?"<>|\s]+/g,'_').replace(/^_+|_+$/g,'').slice(0,100);
      const relative=r.platform==='xhs'?path.join('redis',r.campaign,'专题一',slug+'-'+r.taskId.slice(-12)):
        path.join('tasks',createHash('sha256').update('专题一/'+r.keyword).digest('hex').slice(0,24),r.collectionPass);
      const dbPath=path.resolve(root,'.state',relative,'checkpoint.sqlite');
      if(!dbPath.toLowerCase().startsWith((root+path.sep).toLowerCase()))throw new Error('DATE_CHECKPOINT_OUTSIDE_WORKER');
      if(!fs.existsSync(dbPath))throw new Error('DATE_CHECKPOINT_NOT_FOUND');
      return {...result,...readCheckpointDates(dbPath,r.keyword,platform,r.projects||[])};
    }catch(e){return {...result,errorType:e.code||e.message||'DATE_READ_FAILED'};}
  });
}

if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href){
  console.log(JSON.stringify(readMachineDates(JSON.parse(Buffer.from(process.argv[2],'base64').toString('utf8')),process.argv[3])));
}
