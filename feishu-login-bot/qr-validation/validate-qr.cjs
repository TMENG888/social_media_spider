// Decode only to a yes/no verdict. Never return or log the QR payload.
const fs=require('node:fs');
const {PNG}=require('pngjs');
const jsQR=require('./jsQR.cjs');
try{
 const data=fs.readFileSync(0);
 if(data.length>2000000||data.length<24||data.toString('hex',0,8)!=='89504e470d0a1a0a')throw Error('PNG_REQUIRED');
 const width=data.readUInt32BE(16),height=data.readUInt32BE(20);
 if(width<80||height<80||width>650||height>650)throw Error('DIMENSIONS');
 const png=PNG.sync.read(data,{checkCRC:true});
 let code=jsQR(new Uint8ClampedArray(png.data),png.width,png.height,{inversionAttempts:'attemptBoth'});
 // Element screenshots can crop away the white quiet zone around the symbol.
 // Add a white margin for decoding; the image sent to users remains unchanged.
 if(!code){
  const pad=24,w=png.width+pad*2,h=png.height+pad*2,pixels=new Uint8ClampedArray(w*h*4).fill(255);
  for(let y=0;y<png.height;y++)for(let x=0;x<png.width;x++){
   const from=(y*png.width+x)*4,to=((y+pad)*w+x+pad)*4;
   for(let k=0;k<3;k++)pixels[to+k]=png.data[from+k];
  }
  code=jsQR(pixels,w,h,{inversionAttempts:'attemptBoth'});
 }
 // Small browser screenshots contain antialiased gray module edges. Try a
 // bounded set of contrasts, still requiring a real successful QR decode.
 for(const threshold of [160,128,192]){
  if(code)break;
  const pad=24,w=png.width+pad*2,h=png.height+pad*2,pixels=new Uint8ClampedArray(w*h*4).fill(255);
  for(let y=0;y<png.height;y++)for(let x=0;x<png.width;x++){
   const i=(y*png.width+x)*4,o=((y+pad)*w+x+pad)*4;
   const gray=(png.data[i]+png.data[i+1]+png.data[i+2])/3;
   pixels[o]=pixels[o+1]=pixels[o+2]=gray>=threshold?255:0;
  }
  code=jsQR(pixels,w,h,{inversionAttempts:'attemptBoth'});
 }
 process.stdout.write(code?'1':'0');
}catch{process.stdout.write('0');}
