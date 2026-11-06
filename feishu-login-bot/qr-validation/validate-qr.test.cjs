// Synthetic symbols only; no account login payloads or external connections.
const assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const QRCode=require('qrcode');
const {PNG}=require('pngjs');
const path=require('node:path');
const helper=path.join(__dirname,'validate-qr.cjs');
function verdict(data){
 const p=spawnSync(process.execPath,[helper],{input:data,timeout:10000});
 assert.equal(p.status,0);assert.equal(p.stderr.length,0);
 return p.stdout.toString();
}
(async()=>{
 let passed=0;
 for(const width of [120,240,600]){
  const png=await QRCode.toBuffer('SYNTHETIC-OFFLINE-LOGIN-TEST',{width,margin:4});
  assert.equal(verdict(png),'1');passed++;
 }
 const blank=new PNG({width:180,height:180});blank.data.fill(255);
 assert.equal(verdict(PNG.sync.write(blank)),'0');passed++;
 assert.equal(verdict(Buffer.from('not an image')),'0');passed++;
 assert.equal(verdict(Buffer.alloc(2000001)),'0');passed++;
 for(const width of [60,700]){
  const png=await QRCode.toBuffer('SYNTHETIC-OFFLINE-LOGIN-TEST',{width});
  assert.equal(verdict(png),'0');passed++;
 }
 console.log(JSON.stringify({passed,syntheticOnly:true,qrPayloadNeverReturned:true}));
})().catch(e=>{console.error(e);process.exitCode=1;});
