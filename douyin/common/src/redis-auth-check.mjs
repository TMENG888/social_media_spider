import path from "node:path";
import { fileURLToPath } from "node:url";
import { redisSettings, connectRedis } from "./redis-connection.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
let client;
try {
  client = await connectRedis(await redisSettings(root));
  await client.ping();
  console.log("[Redis authentication] Connection, username and password verified.");
} catch (error) {
  if (/WRONGPASS|invalid username-password pair|user is disabled/i.test(String(error.message || error))) {
    console.error("[Redis authentication] Username/password rejected or ACL user disabled. Update the saved Redis password.");
    process.exitCode = 2;
  } else {
    console.error("[Redis authentication] Connection or configuration check failed. Check the Redis endpoint, service and network.");
    process.exitCode = 3;
  }
} finally {
  await client?.close().catch(() => {});
}
