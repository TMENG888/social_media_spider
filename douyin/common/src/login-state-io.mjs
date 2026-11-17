import {publishOpsState} from './ops-state.mjs';
// Preserve the previous complete state while a Windows/SMB reader holds it open.
import fs from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
export async function atomicLoginState(file,value,{
 writeFile=fs.writeFile,rename=fs.rename,unlink=fs.unlink,
 sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms)),
 delays=[40,80,160,320,500,800]
}={}){
 const tmp=file+'.'+process.pid+'.'+randomUUID()+'.tmp';
 try{
  await writeFile(tmp,JSON.stringify(value),{flag:'wx'});
  for(let attempt=0;;attempt++){
   try{await rename(tmp,file);publishOpsState(file,value);return;}
   catch(error){
    if(!['EPERM','EACCES','EBUSY'].includes(error.code)||attempt>=delays.length)throw error;
    await sleep(delays[attempt]);
   }
  }
 }finally{await unlink(tmp).catch(()=>{});}
}
