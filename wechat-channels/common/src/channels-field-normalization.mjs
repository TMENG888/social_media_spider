// The same deterministic transformations used by ODS export and its verifier.
// No approximate text matching, title-only identity, or invented source text.
import {cleanText,extractHashtags,normalizeTags} from './text-cleaner.mjs';
const cpLength=value=>[...String(value??'')].length;
const hashtagPattern=/(?<![A-Za-z0-9_])#((?:[\p{L}_][^#\s,，;；.!！?？、]{0,49})|(?:\d{2,}[\p{L}\p{N}_·-]{0,48}))/gu;

export function cleanCompactContent(raw){
 const source=String(raw||'')
  .replace(/，?\s*时长\s*\n?\s*\d{1,2}:\d{2}(?::\d{2})?/gu,'')
  .split(/\r?\n/).filter(line=>!/^\s*(?:继续滑动看下一个|向上滑动看下一个|阅读原文|写留言|暂无留言)\s*$/u.test(line)).join('\n');
 const tags=normalizeTags(extractHashtags(source));
 const body=source.replace(hashtagPattern,'$1').replace(/#/gu,'');
 const cleaned=cleanText(body,{removeEmoji:true});
 const compact=cleaned.text.replace(/[\t\r\n]+/g,'').replace(/ {2,}/g,' ').trim();
 const compactRemoved=cpLength(cleaned.text)-cpLength(compact);
 return {content:compact||null,tags,stats:{...cleaned.stats,清理后文字数:cpLength(compact),其他字符个数:cleaned.stats.其他字符个数+Math.max(0,compactRemoved)}};
}

export function cleanVideoContent(raw){
 const source=String(raw||'');
 const withoutBoilerplate=source.replace(/请(?:不吝)?点赞订阅转发打赏支持明镜与点点(?:栏目)?/gu,'');
 let deduped=withoutBoilerplate;
 for(let i=0;i<3;i++){
  const collapsed=deduped.replace(/(.{6,}?[，。！？；])(?:\1)+/gu,'$1');
  if(collapsed===deduped)break;deduped=collapsed;
 }
 const clauses=deduped.split(/[，。！？；]+/gu).map(value=>value.trim()).filter(Boolean),originalClauseCount=clauses.length;
 let changed=true;
 while(changed&&clauses.length>=2){
  changed=false;
  for(let width=Math.floor(clauses.length/2);width>=1&&!changed;width--){
   for(let start=0;start+width*2<=clauses.length;start++){
    if(clauses.slice(start,start+width).join('\u0000')===clauses.slice(start+width,start+width*2).join('\u0000')){
     clauses.splice(start+width,width);changed=true;break;
    }
   }
  }
 }
 if(clauses.length!==originalClauseCount)deduped=clauses.join('，');
 const removedCount=Math.max(0,cpLength(source)-cpLength(deduped));
 const cleaned=cleanText(deduped,{removeEmoji:true,singleParagraph:true,paragraphSeparator:'，'});
 const text=cleaned.text.replace(/，{2,}/gu,'，').replace(/^，|，$/gu,'').trim();
 return {text:text||null,stats:{...cleaned.stats,原始文字数:cpLength(source),清理后文字数:cpLength(text),
  其他字符个数:Number(cleaned.stats.其他字符个数||0)+removedCount,重复字符个数:Number(cleaned.stats.重复字符个数||0)+removedCount}};
}
