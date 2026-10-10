import path from 'node:path';
import {fileURLToPath} from 'node:url';
import fs from 'node:fs/promises';
import readline from 'node:readline/promises';
import {chromium} from 'playwright';
const common=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const index=process.argv.indexOf('--worker-root');
if(index<0||!process.argv[index+1])throw new Error('worker-root is required');
const worker=path.resolve(process.argv[index+1]),profile=path.join(worker,'.state/browser-profile');
await fs.mkdir(profile,{recursive:true});
const context=await chromium.launchPersistentContext(profile,{executablePath:path.join(common,'runtime/browsers/chrome-win64/chrome.exe'),headless:false,viewport:null});
const terminal=readline.createInterface({input:process.stdin,output:process.stdout});
try{
 await (context.pages()[0]||await context.newPage()).goto('https://www.douyin.com',{waitUntil:'domcontentloaded'});
 await terminal.question('Complete Douyin login manually in the browser, then press Enter here. No automatic credential or CAPTCHA entry.\n');
}finally{terminal.close();await context.close();}
