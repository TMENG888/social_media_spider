import mysql from "mysql2/promise";

const host = process.env.MYSQL_HOST || "mysql.example.com";
const port = Number(process.env.MYSQL_PORT || 3306);
const database = process.env.MYSQL_DATABASE || "social";
const user = process.env.MYSQL_USER || "";
const password = process.env.MYSQL_PASSWORD || "";
if (!user || !password) throw new Error("MYSQL_USER 或 MYSQL_PASSWORD 为空");

const connection = await mysql.createConnection({
  host, port, database, user, password, charset: "utf8mb4",
  ssl: /^(1|true|yes)$/i.test(process.env.MYSQL_SSL || "") ? {} : undefined,
  connectTimeout: 15000
});
try {
  await connection.query("SELECT 1");
  console.log(JSON.stringify({ ok: true, host, port, database, credentialsSaved: false }, null, 2));
} finally {
  await connection.end();
}
