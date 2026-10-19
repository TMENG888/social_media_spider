// User-approved on 2026-10-15: enterprise aliases require retained housing
// clues. Only exact enterprise query anchors are eligible; never strip a
// project suffix or infer that an arbitrary subsidiary is the same company.
export const RELEVANCE_POLICY='20261016-enterprise-housing-specific-qualifier-v2';
const normalize=value=>String(value??'').normalize('NFKC').toLowerCase().replace(/[\s\p{P}\p{S}]/gu,'');
const groups=[
 {queries:['保利','保利地产','保利发展','保利发展控股','中国保利集团'],aliases:['保利']},
 {queries:['中海','中海地产','中海企业发展','中国海外发展','中国海外集团'],aliases:['中海','中国海外发展']},
 {queries:['金茂','中国金茂','中国金茂控股'],aliases:['金茂']},
 {queries:['招商','招商地产','招商蛇口','招商局蛇口'],aliases:['招商']},
 {queries:['华润','华润置地'],aliases:['华润']},
 {queries:['中海宏洋','中国海外宏洋'],aliases:['中海宏洋','中国海外宏洋']},
 {queries:['保利置业'],aliases:['保利置业']},
 {queries:['招商局置地'],aliases:['招商局置地']},
 {queries:['招商建管'],aliases:['招商建管']},
 {queries:['富利建设'],aliases:['富利建设']}
];
const housing=/住宅|楼盘|新房|看房|买房|户型|样板间|交房|售楼|精装|房产|地产|楼市|房价|小区/;
// Generic housing/question modifiers are not project names. Any other suffix
// after an enterprise anchor remains a required, retained-content qualifier;
// whitespace in "enterprise project" must never erase the specific project.
const genericModifiers=new Set(['住宅','楼盘','新房','看房','买房','户型','样板间','交房','售楼','精装','房产','地产','楼市','房价','小区',
 '价格','评价','值得买吗','怎么样','口碑','好房子','好社区','产品力','设计','主入口','园林','景观','公区','立面','物业','品质','配套','住宅设计'].map(normalize));
export function entityRelevance(keyword,post={}){
 const tokens=String(keyword??'').trim().split(/\s+/),anchor=tokens[0],key=normalize(anchor);
 const fields={title:post.文章标题??post.title,body:post.文章内容??post.body,
  tags:post.文章标签??post.tags,subtitle:post.文章视频内容??post.subtitle};
 const values=Object.entries(fields).map(([field,value])=>[field,normalize(Array.isArray(value)?value.join(' '):value)]);
 const group=groups.find(g=>g.queries.some(query=>normalize(query)===key));
 const aliases=group?group.aliases:[anchor];
 const requiredQualifier=group?normalize(tokens.slice(1).filter(token=>!genericModifiers.has(normalize(token))).join(' ')):'';
 const qualifierMatches=requiredQualifier?values.filter(([,value])=>value.includes(requiredQualifier)).map(([field])=>({qualifier:requiredQualifier,field})):[];
 const matches=aliases.flatMap(alias=>values.filter(([,value])=>normalize(alias).length>=2&&value.includes(normalize(alias))).map(([field])=>({anchor:alias,field})));
 const labels=group?[...new Set([...group.queries,...group.aliases].map(normalize))].sort((a,b)=>b.length-a.length):[];
 const housingMatches=values.flatMap(([field,value])=>{
  // "地产" inside the enterprise name itself is not an independent housing clue.
  const content=labels.reduce((text,label)=>text.split(label).join(''),value);
  const match=content.match(housing);return match?[{field,clue:match[0]}]:[];
 });
 return {policy:RELEVANCE_POLICY,anchor,enterprise:!!group,aliases,
  accepted:matches.length>0&&(!requiredQualifier||qualifierMatches.length>0)&&(!group||housingMatches.length>0),matches,housingMatches,requiredQualifier:requiredQualifier||null,qualifierMatches,
  reason:!matches.length?'entity_not_observed':requiredQualifier&&!qualifierMatches.length?'project_qualifier_not_observed':group&&!housingMatches.length?'housing_clue_not_observed':group?'enterprise_alias_and_housing_observed':'exact_project_or_entity_observed'};
}
