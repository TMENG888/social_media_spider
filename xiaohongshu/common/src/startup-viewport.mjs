export async function ensureStartupViewport(page,{log=console.log}={}){
 const before=await page.evaluate(()=>({width:window.innerWidth,height:window.innerHeight}));
 if(before.width>=800&&before.height>=600)return {changed:false,before};
 // Run once on connection, before login/search. Never run in the rest/resume
 // callback, never reload or navigate, and do not weaken sort verification.
 await page.setViewportSize({width:1440,height:1000});
 const after=await page.evaluate(()=>({width:window.innerWidth,height:window.innerHeight}));
 log(`[启动窗口核验] 页面可用区域${before.width}×${before.height}，已调整为${after.width}×${after.height}；未刷新页面`);
 if(after.width<800||after.height<600)throw Error('STOP_VIEWPORT_UNUSABLE：页面可用区域仍过小，保留断点停止');
 return {changed:true,before,after};
}
