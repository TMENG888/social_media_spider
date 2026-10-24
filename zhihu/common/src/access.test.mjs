import test from 'node:test';
import assert from 'node:assert/strict';
import {appealSummary,accessIssue} from './access.mjs';
test('REA-observed login gate is distinct from a generic 403',()=>{
 const issue=accessIssue({url:'https://www.zhihu.com/account/unhuman?type=U4E3Z1&need_login=true',httpStatus:403,text:'请您登录后查看更多专业优质内容。'});assert.equal(issue.code,'LOGIN_REQUIRED');
});
test('IP appeal response retains reason without session or IP details',()=>{
 const appeal=appealSummary({block_level:1,redirect_url:'/account/unhuman%3Ftype%3Dabuseip%26message%3D'+encodeURIComponent('当前 IP 被检测到存在异常流量，登录后才能继续访问')});assert.deepEqual(appeal,{blockLevel:1,ipRestricted:true,requiresLogin:true});assert.equal(accessIssue({appeal}).code,'LOGIN_REQUIRED_IP_RESTRICTED');assert(!JSON.stringify(appeal).includes('redirect_url'));
});
test('unknown 403 and challenge retain stopping behavior',()=>{
 assert.equal(accessIssue({httpStatus:403}).code,'RISK_CONTROLLED');assert.equal(accessIssue({url:'https://www.zhihu.com/account/unhuman',text:'完成验证'}).code,'RISK_CONTROLLED');assert.equal(accessIssue({url:'https://www.zhihu.com/search?type=content',httpStatus:200,text:'搜索结果'}),null);
});
