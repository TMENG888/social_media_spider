// Explicit --import fixture for subprocess tests. Never uses a real socket.
import fs from 'node:fs';
import path from 'node:path';
import mysql from 'mysql2/promise';
import {performance} from 'node:perf_hooks';
import {ProductionOutputRecorder} from '../../src/production-output.mjs';
const root=process.env.CHANNELS_MYSQL_TEST_ROOT,mode=process.env.CHANNELS_MYSQL_TEST_MODE;
if(!root||!mode)throw Error('MYSQL_TRANSPORT_FIXTURE_REQUIRES_EXPLICIT_TEST_CONTEXT');
const file=path.join(root,'fake-database.json');
const load=()=>fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{connections:0,commits:0,rows:[],rollbacks:0,active:0,closed:0};
const save=s=>fs.writeFileSync(file,JSON.stringify(s));
ProductionOutputRecorder.prototype.flush=function(){};
const realTimer=globalThis.setTimeout;
const wrapper=process.argv[1]?.endsWith('mysql-import-retry.mjs');
let clock=0;
if(wrapper)Object.defineProperty(performance,'now',{value:()=>clock});
globalThis.setTimeout=(fn,ms,...args)=>{
 if(wrapper&&ms>0&&ms<=120000){
  if(load().active)throw Error('MYSQL_FIXTURE_CONNECTION_HELD_DURING_WAIT');
  clock+=ms;
  if(mode==='stop_wait'&&clock>=20000)fs.writeFileSync(path.join(root,'stop.requested'),'manual-stop');
  return realTimer(fn,0,...args);
 }
 return realTimer(fn,[5000,10000].includes(ms)?0:ms,...args);
};
mysql.createConnection=async()=>{
 const state=load();state.connections++;save(state);const attempt=state.connections;
 const error=code=>Object.assign(Error('fixture-only SQL/password must not leak'),{code});
 if(mode==='dns'&&attempt<3||['exhausted','stop_wait'].includes(mode)||
   mode==='standby_recover'&&attempt<5||['standby_auth','standby_commit_unknown'].includes(mode)&&attempt<4)throw error('ENOTFOUND');
 if(mode==='standby_auth'&&attempt>=4)throw error('ER_ACCESS_DENIED_ERROR');
 if(mode==='auth')throw error('ER_ACCESS_DENIED_ERROR');
 state.active++;save(state);
 let pending=structuredClone(state.rows),inserted=false;
 return {
  async query(sql){
   if(sql.includes('GET_LOCK'))return [[{acquired:mode==='lock'&&attempt===1?0:1}]];
   return [[]];
  },
  async beginTransaction(){},
  async execute(sql,args){
   if(sql.includes('information_schema'))return [[]];
   if(sql.startsWith('INSERT')){
    const fields=sql.match(/\((.*?)\) VALUES/)[1].split(',').map(v=>v.replaceAll('`',''));
    pending.push(Object.fromEntries(fields.map((field,i)=>[field,args[i]])));inserted=true;return [{affectedRows:1}];
   }
   if(mode==='deadlock'&&attempt===1&&inserted)throw error('ER_LOCK_DEADLOCK');
   if(sql.startsWith('UPDATE'))throw Error('Fixture must not replay a committed insert');
   if(sql.startsWith('SELECT')&&sql.includes('WHERE `文章链接`=?'))return [structuredClone(pending.filter(row=>row['文章链接']===args[0]))];
   if(sql.startsWith('SELECT')&&sql.includes('WHERE id=?'))return [structuredClone(pending.filter(row=>String(row.id)===String(args[0])))];
   return [structuredClone(pending)];
  },
  async rollback(){const s=load();s.rollbacks++;save(s);pending=structuredClone(s.rows);},
  async commit(){const s=load();s.rows=pending;s.commits++;save(s);if(['commit_unknown','standby_commit_unknown'].includes(mode))throw error('ECONNRESET');},
  async end(){const s=load();s.active--;s.closed++;save(s);},
 };
};
