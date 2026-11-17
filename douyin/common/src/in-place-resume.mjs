// Read-only wake validation. Never navigate, reload, search or reset a protection.
export async function validateInPlaceResume({page,pauseUrl,shouldStop,verifyLease,verifyControl,checkAccess}){
 const checkStop=async()=>{if(await shouldStop())throw new Error('STOP_REQUESTED：原位恢复前收到停止请求');};
 await checkStop();await verifyLease();await verifyControl();await checkStop();
 if(page.isClosed())throw new Error('STOP_BROWSER_CLOSED：原页面已关闭，保留断点，禁止重新搜索冒充原位恢复');
 if(page.url()!==pauseUrl)throw new Error('STOP_RESUME_PAGE_CHANGED：休息期间页面地址改变，保留断点并停止');
 await checkAccess(page);await checkStop();
}
