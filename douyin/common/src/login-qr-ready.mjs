const delay=ms=>new Promise(r=>setTimeout(r,ms));
export async function resolveLoginQr({page,findQr,canOpen=true,wait=delay}){
 // A reload may show the modal before its QR image finishes loading. Give it
 // time and inspect the already open scan pane before clicking a login entry.
 for(let i=0;i<6;i++){const qr=await findQr();if(qr)return qr;await wait(250);}
 if(!canOpen)return null;
 const scan=page.getByText('扫码登录',{exact:true});let scanVisible=false;
 for(let i=0;i<Math.min(await scan.count(),12);i++)if(await scan.nth(i).isVisible().catch(()=>false))scanVisible=true;
 for(const text of scanVisible?['扫码登录']:['扫码登录','登录']){
  const candidates=page.getByText(text,{exact:true});
  for(let i=0;i<Math.min(await candidates.count(),8);i++){
   const button=candidates.nth(i);if(!await button.isVisible().catch(()=>false))continue;
   try{await button.click({timeout:2000});}catch(e){if(page.isClosed())throw e;}
   for(let n=0;n<4;n++){await wait(250);const qr=await findQr();if(qr)return qr;}
  }
 }
 return null;
}
