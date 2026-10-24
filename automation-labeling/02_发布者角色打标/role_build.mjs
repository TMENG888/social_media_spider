import fs from 'node:fs/promises';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const out=process.env.ROLE_TEST_OUTPUT||'D:/Codex/outputs/01a1349d-c76e-7b63-be36-3c8e0766deef/20261014_发布者角色各50条盲测';
const d=JSON.parse(await fs.readFile(out+'/comparison_data.json','utf8'));
const wb=Workbook.create(),s=wb.worksheets.add('评估汇总'),t=wb.worksheets.add('逐条对照'),r=wb.worksheets.add('共同输入');
const literal=x=>typeof x==='string'&&x.startsWith('=')?"'"+x:x;
const put=(sh,range,data)=>sh.getRange(range).values=data.map(row=>row.map(literal));
const head=(sh,range)=>{sh.getRange(range).format.fill='#203B53';sh.getRange(range).format.font={name:'Arial',size:10,bold:true,color:'#FFFFFF'};sh.getRange(range).format.wrapText=true;sh.getRange(range).format.rowHeight=32;sh.getRange(range).format.horizontalAlignment='center';};
for(const sh of [s,t,r]){sh.showGridLines=false;sh.getRange('A1:U110').format.font={name:'Arial',size:10};sh.getRange('A1:U110').format.rowHeight=25;sh.getRange('A1:U110').format.columnWidth=16;sh.getRange('A1:U110').format.verticalAlignment='center';}
put(t,'A2',[['发布者角色：Codex 与 Qwen 全文复测']]);put(t,'A3',[['本轮参考值在新Qwen调用前冻结，但已看过上一轮结果，不是全新盲测。黄色两列供人工反馈。']]);
put(t,'A5:U105',[d.headers,...d.rows]);head(t,'A5:U5');t.tables.add('A5:U105',true,'RoleComparison');t.freezePanes.freezeRows(5);t.freezePanes.freezeColumns(3);
t.getRange('D6:E105').setNumberFormat('@');t.getRange('D5:E105').format.columnWidth=24;t.getRange('F5:F105').format.columnWidth=26;t.getRange('G5:G105').format.columnWidth=44;t.getRange('H5:I105').format.columnWidth=30;t.getRange('K5:N105').format.columnWidth=58;t.getRange('O5:P105').format.columnWidth=20;t.getRange('Q5:Q105').format.columnWidth=35;t.getRange('R5:T105').format.columnWidth=30;
t.getRange('A6:U105').format.wrapText=true;t.getRange('A6:U105').format.verticalAlignment='top';t.getRange('A6:U105').format.rowHeight=80;t.getRange('U5:U105').format.columnWidth=60;
for(let i=0;i<d.rows.length;i++){const chars=Math.max(...[10,11,12,13,20].map(c=>String(d.rows[i][c]??'').length));t.getRange(`A${i+6}:U${i+6}`).format.rowHeight=Math.min(400,Math.max(70,Math.ceil(chars/25)*13+16));}
t.getRange('J6:J105').conditionalFormats.add('cellIs',{operator:'equal',formula:'"不一致"',format:{fill:'#FCE4D6'}});
const roles=['品牌、区域公司、项目官方','媒体及专业机构','普通账号','身份不明'];t.getRange('S6:S105').dataValidation={rule:{type:'list',values:roles}};t.getRange('S6:T105').format.fill='#FFF2CC';
put(r,'A2',[['双方共同输入的完整原始字段']]);
put(r,'A3',[['专题一来源：'+d.manifest[0].source]]);put(r,'A4',[['专题二来源：'+d.manifest[1].source]]);
put(r,'A6:N106',[['样本号','数据集','源CSV行号','数据库行ID','文章ID','平台','作者名字','作者主页链接','文章标题','文章标签','文章内容','文章视频内容','文章图片信息','截取字段'],...d.packets.map(p=>{const v=d.raw.find(x=>x.sample_id===p.sample_id);return [p.sample_id,p.dataset,v.source_line,v.row.id,v.row['文章id'],p.fields['平台'],p.fields['作者名字'],p.fields['作者主页链接'],p.fields['文章标题'],p.fields['文章标签'],p.fields['文章内容'],p.fields['文章视频内容'],p.fields['文章图片信息'],p.truncated_fields.join(',')];})]);
head(r,'A6:N6');r.tables.add('A6:N106',true,'RoleInputs');r.freezePanes.freezeRows(6);r.freezePanes.freezeColumns(2);r.getRange('D7:E106').setNumberFormat('@');r.getRange('G6:G106').format.columnWidth=28;r.getRange('H6:J106').format.columnWidth=36;r.getRange('K6:M106').format.columnWidth=70;r.getRange('A7:N106').format.wrapText=true;r.getRange('A7:N106').format.verticalAlignment='top';r.getRange('A7:N106').format.rowHeight=90;
r.getRange('D6:E106').format.columnWidth=28;r.getRange('K6:M106').format.columnWidth=120;
for(let i=0;i<d.packets.length;i++){const f=d.packets[i].fields;const n=Math.max(...['文章内容','文章视频内容','文章图片信息'].map(k=>String(f[k]).length));r.getRange(`A${i+7}:N${i+7}`).format.rowHeight=Math.min(409,Math.max(80,Math.ceil(n/57)*13+14));}
put(s,'A2',[['发布者角色识别：两专题各50条全文复测']]);s.getRange('A2').format.font={name:'Arial',size:14,bold:true};
put(s,'A4:B7',[
 ['参考口径','Codex全文复核，非人工金标准。已看过旧结果，不是全新盲测；一致率不等于真实身份准确率。'],
 ['随机抽样','两个数据集各5平台，每平台随机10条；种子20261014、20261015。不代表全量平台加权表现。'],
 ['输入边界','使用完整正文、视频转写、图片信息及账号字段，不截断。100条输入逐字段核验；超限明确失败。不查认证。'],
 ['角色口径','官方机构 / 媒体及专业机构 / 普通账号 / 身份不明。个人销售、中介和专业创作者归专业类，不能因品牌名断定官方。']]);
s.getRange('A4:A7').format.columnWidth=19;s.getRange('B4:B7').format.columnWidth=65;s.getRange('B4:B7').format.wrapText=true;s.getRange('A4:B7').format.rowHeight=48;
put(s,'A10:H10',[['数据集','样本数','角色非空','一致数','一致率','Codex身份不明','Qwen身份不明','建议复核']]);head(s,'A10:H10');
for(let i=0;i<3;i++){
 const row=11+i,ds=['专题一','专题二','合计'][i];put(s,`A${row}`,[[ds]]);
 const scope=ds==='合计'?'':`'逐条对照'!$B$6:$B$105,A${row},`;
 s.getRange(`B${row}:H${row}`).formulas=[[
 ds==='合计'?"=ROWS('逐条对照'!A6:A105)":`=COUNTIFS('逐条对照'!$B$6:$B$105,A${row})`,
 `=COUNTIFS(${scope}'逐条对照'!$I$6:$I$105,"<>",'逐条对照'!$I$6:$I$105,"<>请求失败")`,
 `=COUNTIFS(${scope}'逐条对照'!$J$6:$J$105,"一致")`,
 `=D${row}/B${row}`,
 `=COUNTIFS(${scope}'逐条对照'!$H$6:$H$105,"身份不明")`,
 `=COUNTIFS(${scope}'逐条对照'!$I$6:$I$105,"身份不明")`,
 `=COUNTIFS(${scope}'逐条对照'!$P$6:$P$105,"是")`]];
}
s.getRange('E11:E13').setNumberFormat('0.0%');
put(s,'A16:E16',[['平台','专题一样本','专题一一致率','专题二样本','专题二一致率']]);head(s,'A16:E16');
for(let i=0;i<5;i++){
 const row=17+i;put(s,`A${row}`,[[['小红书','微信公众号','微信视频号','抖音','网页'][i]]]);
 for(const [ds,countC,rateC] of [['专题一','B','C'],['专题二','D','E']]){
  const criteria=`'逐条对照'!$B$6:$B$105,"${ds}",'逐条对照'!$C$6:$C$105,A${row}`;
  s.getRange(`${countC}${row}`).formulas=[[`=COUNTIFS(${criteria})`]];
  s.getRange(`${rateC}${row}`).formulas=[[`=COUNTIFS(${criteria},'逐条对照'!$J$6:$J$105,"一致")/${countC}${row}`]];
 }
}
s.getRange('C17:C21').setNumberFormat('0.0%');s.getRange('E17:E21').setNumberFormat('0.0%');
put(s,'A24:F24',[['参考角色（合计）','Codex数量','Qwen数量','同类命中','对参考精确率','对参考召回率']]);head(s,'A24:F24');s.getRange('A24:A28').format.columnWidth=34;
for(let i=0;i<4;i++){
 const row=25+i;put(s,`A${row}`,[[roles[i]]]);s.getRange(`B${row}:F${row}`).formulas=[[
 `=COUNTIFS('逐条对照'!$H$6:$H$105,A${row})`,
 `=COUNTIFS('逐条对照'!$I$6:$I$105,A${row})`,
 `=COUNTIFS('逐条对照'!$H$6:$H$105,A${row},'逐条对照'!$I$6:$I$105,A${row})`,
 `=IF(C${row}=0,"n.a.",D${row}/C${row})`,
 `=IF(B${row}=0,"n.a.",D${row}/B${row})`]];
}
s.getRange('E25:F28').setNumberFormat('0.0%');
put(s,'A31',[['混淆矩阵：行=Codex，列=Qwen（全部100条）']]);put(s,'A33:E37',[['Codex / Qwen',...roles],...roles.map(x=>[x,null,null,null,null])]);head(s,'A33:E33');s.getRange('A33:A37').format.columnWidth=34;s.getRange('B33:E33').format.columnWidth=29;s.getRange('A33:E33').format.rowHeight=45;
for(let i=0;i<4;i++)for(let j=0;j<4;j++){const row=34+i,c=String.fromCharCode(66+j);s.getRange(`${c}${row}`).formulas=[[`=COUNTIFS('逐条对照'!$H$6:$H$105,$A${row},'逐条对照'!$I$6:$I$105,${c}$33)`]];}
const cost=d.cost;put(s,'A40:B50',[
 ['Qwen模型',d.run.model],['并发',d.run.concurrency],['实际HTTP尝试数',cost.attempts],['输入 / 输出Token',`${cost.prompt_tokens} / ${cost.completion_tokens}`],['总Token',cost.prompt_tokens+cost.completion_tokens],['缓存输入Token',cost.cached_tokens],['已知估算费用（元）',cost.known_estimated_yuan],['未知usage / 费用尝试',`${cost.unknown_usage_attempts} / ${cost.unknown_cost_attempts}`],['调用墙钟耗时（秒）',cost.wall_seconds],['累计请求耗时（秒）',cost.request_seconds],['费用说明','沿用现有Qwen程序单价估算，含重试，不是网关实际账单；不含Codex预判成本。']]);s.getRange('B46').setNumberFormat('0.000000');s.getRange('B48:B49').setNumberFormat('0.00');s.getRange('B50').format.wrapText=true;s.getRange('A50:B50').format.rowHeight=45;
put(s,'A53:B57',[
 ['身份核验限制','原CSV未提供认证主体/简介；官方类都是文本推断，不是认证核验。'],
 ['格式归一','Qwen子类“品牌/区域公司/项目官方”合并到用户第一大类，保留原始响应；不改模型判断语义。'],
 ['全文读取','共同输入保留完整文本。长单元格显示高度有限，点击单元格可在编辑栏读取全部内容。'],
 ['复核建议','先人工看不一致项，再看官方、身份不明及专业/普通边界；反馈填写逐条对照的两列。'],
 ['范围','仅样本新字段测试，原CSV与数据库未修改；不是全量每条数据打标交付。']]);s.getRange('B53:B57').format.wrapText=true;s.getRange('A53:B57').format.rowHeight=45;
for(const row of [4,5,6,7,50,53,54,55,56,57]){s.mergeCells(`B${row}:H${row}`);s.getRange(`B${row}:H${row}`).format.wrapText=true;}
put(s,'A60:B66',[
 ['同样100条复测','保留原样本及原截取版，源CSV和数据库未修改。'],
 ['旧版一致数',d.retest.old_agree],
 ['全文对旧参考一致数',d.retest.new_agree_fixed_old_reference],
 ['全文对修订参考一致数',d.retest.new_agree_revised_reference],
 ['Qwen标签变化数',d.retest.qwen_changed.length],
 ['参考标签修订','1-23、2-29由专业类修订为身份不明，不能把参考变化算成全文输入带来的改善。'],
 ['证据逐字校验通过数',d.stats[2].evidence_pass]]);
for(const row of [60,65]){s.mergeCells(`B${row}:H${row}`);s.getRange(`B${row}:H${row}`).format.wrapText=true;s.getRange(`A${row}:H${row}`).format.rowHeight=45;}
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'评估汇总!A10:H13',include:'values,formulas',tableMaxRows:4,tableMaxCols:8,maxChars:4500})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!',options:{useRegex:true,maxResults:20},maxChars:1500})).ndjson);
for(const [sh,range,name] of [[s,'A2:H7','口径'],[s,'A60:H66','新旧比较'],[s,'A10:H28','汇总'],[s,'A31:E37','混淆矩阵'],[t,'F5:J10','对照'],[r,'A6:G11','共同输入'],[r,'K20:M21','全文']]){const b=await wb.render({sheetName:sh.name,range,scale:1,format:'png'});await fs.writeFile(out+'/preview_'+name+'.png',new Uint8Array(await b.arrayBuffer()));}
await (await SpreadsheetFile.exportXlsx(wb)).save(out+'/发布者角色_Codex与Qwen_两专题各50条全文复测.xlsx');
