import dns from 'node:dns/promises';
import net from 'node:net';
import {execFile} from 'node:child_process';

export const NETWORK_RETRY_VERSION='redis-network-aware-20261113-v1';
// The selected route/interface, rather than a Wi-Fi name or internet website,
// determines whether the LAN path exists. No Redis protocol or platform access.
export async function windowsRoute(address){
  if(!net.isIP(address))return {state:'unknown',reason:'invalid_address'};
  const family=net.isIP(address)===6?'IPv6':'IPv4';
  const script=`$ErrorActionPreference='Stop';try{
    $connected=@(Get-NetIPInterface -AddressFamily ${family} -ErrorAction Stop|Where-Object {$_.ConnectionState -eq 'Connected'}|ForEach-Object {$_.InterfaceIndex})
    $addresses=@(Get-NetIPAddress -AddressFamily ${family} -ErrorAction Stop|Where-Object {$_.InterfaceIndex -in $connected -and $_.AddressState -in @('Preferred','Deprecated') -and $_.IPAddress -notmatch '^(127\\.|169\\.254\\.|::1$|fe80:)'})
    if($addresses.Count -eq 0){@{state='offline';reason='no_connected_interface'}|ConvertTo-Json -Compress;exit}
    $route=@(Find-NetRoute -RemoteIPAddress '${address}' -ErrorAction Stop)
    $indices=@($route|ForEach-Object {$_.InterfaceIndex})
    if(@($addresses|Where-Object {$_.InterfaceIndex -in $indices}).Count -gt 0){@{state='ready';reason='route_connected'}|ConvertTo-Json -Compress}
    else{@{state='offline';reason='route_disconnected'}|ConvertTo-Json -Compress}
  }catch{@{state='unknown';reason='route_check_unavailable'}|ConvertTo-Json -Compress}`;
  return new Promise(resolve=>execFile('powershell.exe',['-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',Buffer.from(script,'utf16le').toString('base64')],
    {windowsHide:true,timeout:5000,maxBuffer:65536,encoding:'utf8'},(error,stdout)=>{
      try{
        const value=JSON.parse(stdout.replace(/^\uFEFF/,''));
        if(!error&&['ready','offline','unknown'].includes(value.state)&&/^[a-z_]+$/.test(value.reason))return resolve(value);
      }catch{}
      resolve({state:'unknown',reason:'route_check_unavailable'});
    }));
}
export async function probeRedisNetwork(settings,{platform=process.platform,lookup=dns.lookup,inspectRoute=windowsRoute}={}){
  let host;
  try{host=new URL(settings?.url).hostname.replace(/^\[|\]$/g,'');}catch{return {state:'unknown',reason:'endpoint_unavailable'};}
  if(host==='localhost'||host==='::1'||/^127\./.test(host))return {state:'ready',reason:'loopback'};
  let address=host,timer;
  if(!net.isIP(address)){
    try{
      const result=await Promise.race([lookup(host),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('DNS_TIMEOUT')),2000);})]);
      address=result.address;
    }catch{return {state:'unknown',reason:'dns_check_unavailable'};}
    finally{clearTimeout(timer);}
  }
  if(platform!=='win32')return {state:'unknown',reason:'route_check_unsupported'};
  try{return await inspectRoute(address);}catch{return {state:'unknown',reason:'route_check_unavailable'};}
}
