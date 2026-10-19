// One target for import, preflight and independent readback. Deployment may
// retain its existing non-secret coordinates in mysql-defaults.json; secrets
// remain exclusively in the calling process environment.
import {readFileSync} from 'node:fs';
const defaults=JSON.parse(readFileSync(new URL('./mysql-defaults.json',import.meta.url),'utf8').replace(/^\uFEFF/,''));
export function mysqlConnectionOptions(env=process.env){
 const host=env.MYSQL_HOST||defaults.host;
 const port=Number(env.MYSQL_PORT||defaults.port);
 const database=env.MYSQL_DATABASE||defaults.database;
 if(!host||!database||!Number.isInteger(port)||port<1||port>65535)throw new Error('MYSQL_TARGET_INVALID');
 if(!env.MYSQL_USER||!env.MYSQL_PASSWORD)throw new Error('MYSQL_CREDENTIALS_MISSING');
 return {host,port,database,user:env.MYSQL_USER,password:env.MYSQL_PASSWORD,
  charset:'utf8mb4',connectTimeout:15000,
  ssl:/^(1|true|yes)$/i.test(env.MYSQL_SSL||'')?{}:undefined};
}
