// XHS/Douyin and Channels write the same ODS tables. Acquire the existing
// cross-platform lock FIRST, then retain the legacy Channels lock so older
// Channels writers still serialize. No table/server settings are changed.
export const IMPORT_LOCK_ORDER=Object.freeze(['social_xhs_distributed_import','wechat_ods_import']);
export async function acquireImportLocks(connection,{timeoutSeconds=60}={}){
 if(!Number.isSafeInteger(timeoutSeconds)||timeoutSeconds<0||timeoutSeconds>120)
  throw new Error('IMPORT_LOCK_TIMEOUT_INVALID');
 const held=[];
 const release=async()=>{
  while(held.length){
   const name=held.pop();
   try{await connection.query('SELECT RELEASE_LOCK(?) AS released',[name]);}
   catch{/* Closing this dedicated importer connection also releases its locks. */}
  }
 };
 try{
  for(const name of IMPORT_LOCK_ORDER){
   const [rows]=await connection.query('SELECT GET_LOCK(?, ?) AS acquired',[name,timeoutSeconds]);
   if(Number(rows[0]?.acquired)!==1)throw Object.assign(new Error('MYSQL_IMPORT_LOCK_TIMEOUT: shared ODS import busy; no writes performed'),{code:'MYSQL_IMPORT_LOCK_TIMEOUT'});
   held.push(name);
  }
  return release;
 }catch(error){await release();throw error;}
}
