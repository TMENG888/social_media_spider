import {createHash} from 'node:crypto';

export const MEDIA_BINDING_VERSION='20261015-note-bound-media-v1';
export const mediaHash=value=>createHash('sha256').update(String(value||'')).digest('hex');
const normalize=value=>String(value||'').replace(/\s+/g,'').trim();
const usableUrl=value=>{try{const u=new URL(value);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password;}catch{return false;}};

// Called inside the visible detail root. Never inspect performance history,
// scripts, recommendations or media belonging to another noteDetailMap entry.
export function currentMediaSnapshot(root,noteId) {
  const state=globalThis.__INITIAL_STATE__||{};
  const entry=state.note?.noteDetailMap?.[noteId]||state.noteDetailMap?.[noteId];
  const note=entry?.note||entry?.noteCard||entry||null;
  const video=root.querySelector('video');
  const routeId=location.pathname.match(/\/(?:explore|search_result)\/([a-f0-9]{24})(?:\/|$)/i)?.[1]||null;
  return {noteId,routeId,domNoteId:root.dataset?.noteId||video?.closest('[data-note-id]')?.dataset.noteId||null,
    visibleTitle:root.querySelector('#detail-title,h1.title')?.textContent||'',
    visibleBody:root.querySelector('#detail-desc,.desc')?.textContent||'',
    videoSrc:video?.currentSrc||video?.src||video?.querySelector('source')?.src||null,
    pageDuration:Number.isFinite(video?.duration)&&video.duration>0?video.duration:null,
    recordId:note?.noteId||note?.note_id||note?.id||null,
    recordTitle:note?.title||'',recordBody:note?.desc||'',video:note?.video||null};
}

export function bindCurrentMedia(snapshot) {
  const s=snapshot||{},noteId=String(s.noteId||'');
  const reject=reason=>({ok:false,reason,noteId,version:MEDIA_BINDING_VERSION});
  if(!/^[a-f0-9]{24}$/i.test(noteId))return reject('MEDIA_NOTE_ID_INVALID');
  if([s.routeId,s.domNoteId].some(id=>id&&id!==noteId))return reject('MEDIA_DETAIL_ID_MISMATCH');
  const exactRecord=s.recordId===noteId;
  if(!exactRecord)return reject('MEDIA_EXACT_NOTE_METADATA_MISSING');
  const textMatches=exactRecord&&(
    (normalize(s.visibleTitle)&&normalize(s.visibleTitle)===normalize(s.recordTitle))||
    (normalize(s.visibleBody).length>=8&&normalize(s.visibleBody)===normalize(s.recordBody)));
  if(![s.routeId,s.domNoteId].includes(noteId)&&!textMatches)return reject('MEDIA_VISIBLE_ID_UNVERIFIED');
  const urls=[],seen=new Set();
  const walk=(value,depth=0)=>{
    if(depth>10||value==null)return;
    if(typeof value==='string'){if(usableUrl(value))urls.push(value);return;}
    if(typeof value!=='object'||seen.has(value))return;
    seen.add(value);for(const [key,item] of Object.entries(value)){
      // Video cover, author/avatar and recommendations are not audio sources.
      if(/cover|image|avatar|author|recommend|related/i.test(key))continue;
      if(typeof item==='string'&&!/url|src|master|backup|play/i.test(key))continue;
      walk(item,depth+1);
    }
  };
  if(exactRecord)walk(s.video);
  const candidates=[...new Set(urls)].filter(url=>!/(?:\.(?:jpe?g|png|webp|gif))(?:\?|$)/i.test(url));
  candidates.sort((a,b)=>(/\.mp4(?:\?|$)/i.test(b)?1:0)-(/\.mp4(?:\?|$)/i.test(a)?1:0));
  // URL/route changes alone do not prove that the DOM player has switched.
  // Require the exact note's stream, never use an uncorroborated rendered src.
  const direct=usableUrl(s.videoSrc)?s.videoSrc:null;
  const url=candidates.includes(direct)?direct:candidates[0]||null;
  if(!url)return reject('MEDIA_BOUND_SOURCE_MISSING');
  const expectedDuration=Number(s.pageDuration);
  if(!Number.isFinite(expectedDuration)||expectedDuration<=0)return reject('MEDIA_DURATION_UNOBSERVED');
  return {ok:true,url,binding:{version:MEDIA_BINDING_VERSION,noteId,source:exactRecord?'exact_note_metadata':'visible_video_src',
    urlHash:mediaHash(url),expectedDuration,identityVerified:true}};
}

export function assertMediaProvenance(binding,{noteId,url,duration}={}) {
  if(binding?.version!==MEDIA_BINDING_VERSION||binding.identityVerified!==true||binding.noteId!==noteId||binding.urlHash!==mediaHash(url))
    throw new Error('MEDIA_BINDING_UNVERIFIED: current-note source evidence required');
  const expected=Number(binding.expectedDuration),actual=Number(duration);
  if(!(expected>0)||!(actual>0)||Math.abs(expected-actual)>Math.max(2,expected*.03))
    throw new Error('MEDIA_SOURCE_DURATION_MISMATCH: decoded media does not match visible video');
  return {...binding,decodedDuration:actual,durationVerified:true};
}
