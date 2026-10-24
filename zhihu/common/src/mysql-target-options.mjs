// Shared non-secret target for preflight, import and database readback.
// Explicit process environment overrides deployment defaults.
import {readFileSync} from 'node:fs';
const defaults=JSON.parse(readFileSync(new URL('./mysql-defaults.json',import.meta.url),'utf8').replace(/^\uFEFF/,''));
export function mysqlTargetOptions(env=process.env){
  const host=String(env.MYSQL_HOST||defaults.host||'');
  const port=Number(env.MYSQL_PORT||defaults.port);
  const database=String(env.MYSQL_DATABASE||defaults.database||'');
  if(!host.trim()||!database.trim()||!Number.isInteger(port)||port<1||port>65535)throw new Error('MYSQL_TARGET_INVALID');
  return {host,port,database};
}
