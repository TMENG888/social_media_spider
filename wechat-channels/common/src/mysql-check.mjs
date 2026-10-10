import fs from 'node:fs';
import path from 'node:path';
import mysql from 'mysql2/promise';
import { atomicWriteFileSync } from './atomic-file.mjs';

const args = {};
for (let i = 2; i < process.argv.length; i += 1) {
  if (process.argv[i].startsWith('--')) args[process.argv[i].slice(2)] = process.argv[++i];
}
const host = process.env.MYSQL_HOST || 'mysql.example.com';
const port = Number(process.env.MYSQL_PORT || 3306);
const database = process.env.MYSQL_DATABASE || 'social';
const user = process.env.MYSQL_USER;
const password = process.env.MYSQL_PASSWORD;
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
  connection = await mysql.createConnection({
    host, port, user, password, database, charset: 'utf8mb4',
    connectTimeout: 15000,
    ssl: /^(1|true|yes)$/i.test(process.env.MYSQL_SSL || '') ? {} : undefined,
  });
  await connection.query('SELECT 1 AS connection_ok');
  await connection.query('SELECT 1 FROM `ods_social_media_post` LIMIT 0');
  await connection.query('SELECT 1 FROM `ods_social_media_comment` LIMIT 0');
  await connection.query('SHOW GRANTS');
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
    error: String(error?.message || error),
    checkedAt: new Date().toISOString(),
  };
  writeStatus(status);
  console.error(JSON.stringify(status));
  process.exitCode = 2;
} finally {
  await connection?.end().catch(() => {});
}
