import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {mysqlConnectionOptions} from '../src/mysql-connection-options.mjs';
test('all database clients share one target, with explicit environment override and TLS',async()=>{
 const defaults=JSON.parse(await fs.readFile(new URL('../src/mysql-defaults.json',import.meta.url),'utf8'));
 const credentials={MYSQL_USER:'fixture-user',MYSQL_PASSWORD:'fixture-password'};
 const fallback=mysqlConnectionOptions(credentials);
 assert.equal(fallback.host,defaults.host);assert.equal(fallback.port,defaults.port);assert.equal(fallback.database,defaults.database);
 const explicit=mysqlConnectionOptions({...credentials,MYSQL_HOST:'fixture.example',MYSQL_PORT:'3307',MYSQL_DATABASE:'fixture-db',MYSQL_SSL:'true'});
 assert.equal(explicit.host,'fixture.example');assert.equal(explicit.port,3307);assert.equal(explicit.database,'fixture-db');assert.deepEqual(explicit.ssl,{});
 for(const file of ['mysql-import.mjs','mysql-check.mjs','verify-keyword-coverage.mjs']){
  const source=await fs.readFile(new URL('../src/'+file,import.meta.url),'utf8');
  assert.match(source,/from ['"]\.\/mysql-connection-options\.mjs['"]/);
  assert.doesNotMatch(source,/process\.env\.MYSQL_HOST/);
 }
});
test('missing credentials and invalid target fail closed without including credentials in errors',()=>{
 assert.throws(()=>mysqlConnectionOptions({}),/MYSQL_CREDENTIALS_MISSING/);
 for(const port of ['0','65536','NaN','3.5'])assert.throws(()=>mysqlConnectionOptions({MYSQL_USER:'fixture',MYSQL_PASSWORD:'secret',MYSQL_PORT:port}),/^Error: MYSQL_TARGET_INVALID$/);
});
