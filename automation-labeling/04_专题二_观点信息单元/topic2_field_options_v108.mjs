// T2 field contract: voc_metadata_completion_v99.ALLOWED and product800.ROLES.
// Validate exact values; never silently map a model response to another category.
export const FIELD_OPTIONS=Object.freeze({
 '表达类型':Object.freeze(['事实介绍','正向评价','负向评价','中性评价','需求表达','提问咨询','比较评价']),
 '情绪态度':Object.freeze(['无态度','中性','正向','负向']),
 '发布者角色':Object.freeze(['品牌、区域公司、项目官方','媒体及专业机构','普通账号','身份不明']),
});
export function validateFieldValue(field,value,identity=''){
 const allowed=FIELD_OPTIONS[field];
 if(!allowed)throw Error('Unknown categorical field '+field);
 const parts=typeof value==='string'?value.split(';'):[];
 if(!parts.length||parts.some(p=>!allowed.includes(p))||new Set(parts).size!==parts.length||
    (field==='发布者角色'&&parts.length!==1))
  throw Error(`Invalid ${field} for ${identity}: ${JSON.stringify(value)}; allowed: ${allowed.join(' / ')}`);
 return true;
}
export function validateDeliveryFields(x){
 for(const row of x.units??[])
  for(const field of Object.keys(FIELD_OPTIONS))validateFieldValue(field,row[field],row['切片ID']??row.record_id);
 for(const source of x.sources??[])validateFieldValue('发布者角色',source.publisher,source.record_id);
}
