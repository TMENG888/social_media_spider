import fs from 'node:fs';
import path from 'node:path';
import mysql from 'mysql2/promise';
import { atomicWriteFileSync } from './atomic-file.mjs';
import {mysqlConnectionOptions} from './mysql-connection-options.mjs';
import {retryInfrastructure,safeInfrastructureCode} from './infrastructure-retry.mjs';

const args = {};
for (let i = 2; i < process.argv.length; i += 1) {
  if (process.argv[i].startsWith('--')) args[process.argv[i].slice(2)] = process.argv[++i];
}
const connectionOptions=mysqlConnectionOptions();
const {host,port,database,user,password}=connectionOptions;
const statusFile = args.status ? path.resolve(args.status) : null;
const writeStatus = (status) => {
  if (statusFile) {
    fs.mkdirSync(path.dirname(statusFile), {recursive: true});
    atomicWriteFileSync(statusFile, JSON.stringify(status, null, 2), 'utf8');
  }
};

if (!user || !password) throw new Error('MYSQL_USER and MYSQL_PASSWORD are required');
let connection;
try {
 await retryInfrastructure(async()=>{
  try{
  connection = await mysql.createConnection(connectionOptions);
  await connection.query('SELECT 1 AS connection_ok');
  await connection.query('SELECT 1 FROM `ods_social_media_post` LIMIT 0');
  await connection.query('SELECT 1 FROM `ods_social_media_comment` LIMIT 0');
  await connection.query('SHOW GRANTS');
  }finally{await connection?.end().catch(()=>{});connection=null;}
 },{operation:'mysql_preflight'});
  const status = {
    status: 'success', host, port, database,
    tables: ['ods_social_media_post', 'ods_social_media_comment'],
    checkedAt: new Date().toISOString(),
  };
  writeStatus(status);
  console.log(JSON.stringify(status));
} catch (error) {
  const status = {
    status: 'failed', host, port, database,
    error: safeInfrastructureCode(error),errorCode:safeInfrastructureCode(error),
    checkedAt: new Date().toISOString(),
  };
  writeStatus(status);
  console.error(JSON.stringify(status));
  process.exitCode = 2;
} finally {
  await connection?.end().catch(() => {});
}
