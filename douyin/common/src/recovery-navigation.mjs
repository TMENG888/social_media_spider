// Bounded retries preserve the same browser/profile and all incident guards.
export async function openRecoveryPage(page,url,{assertAllowed,delay=ms=>new Promise(r=>setTimeout(r,ms)),attempts=4}={}){
 const expected=new URL(url);
 if(expected.protocol!=='https:'||!/(^|\.)(xiaohongshu|douyin)\.com$/i.test(expected.hostname))throw Error('RECOVERY_PLATFORM_URL_REQUIRED');
 for(let i=0;i<attempts;i++){
  await assertAllowed();if(page.isClosed())throw Error('STOP_BROWSER_CLOSED');
  try{return await page.goto(url,{waitUntil:'domcontentloaded',timeout:30000});}
  catch(error){
   await assertAllowed();if(page.isClosed())throw Error('STOP_BROWSER_CLOSED');
   // ERR_ABORTED can accompany a completed same-page app navigation.
   if(/net::ERR_ABORTED/.test(error.message||'')){
    try{const current=new URL(page.url());if(current.protocol==='https:'&&current.hostname===expected.hostname&&current.pathname===expected.pathname&&await page.evaluate(()=>document.readyState!=='loading'&&Boolean(document.body?.children.length)))return null;}catch{}
   }
   if(!/net::ERR_(ABORTED|CONNECTION_RESET|TIMED_OUT|CONNECTION_CLOSED|NETWORK_CHANGED)|Timeout|timeout/i.test(error.message||'')||i===attempts-1){
    if(i===attempts-1){const failure=Error('RECOVERY_NAVIGATION_FAILED');failure.code='RECOVERY_NAVIGATION_FAILED';throw failure;}
    throw error;
   }
   for(let elapsed=0;elapsed<(i+1)*2000;elapsed+=250){await assertAllowed();await delay(250);}
  }
 }
}
