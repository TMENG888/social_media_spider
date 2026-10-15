import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";

const root = process.cwd();
const outputRoot = path.join(root, "分布式部署包");
const nodeSource = process.env.NODE_RUNTIME_SOURCE || process.execPath;
const browserSource = path.join(root, ".portable-build/browsers");
const taskRoot = path.join(root, "检索词任务");
const topic2TaskRoot = process.env.TOPIC2_TASK_ROOT || path.join(root, "检索词任务", "topic2");
const version = `portable-1.0.0-${new Date().toISOString().replace(/[-:]/g, "").slice(0, 15)}Z`;
const launchBat = [
  "@echo off", "chcp 65001 >nul", "setlocal", "set \"SCRIPT_DIR=%~dp0\"",
  "\"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe\" -NoLogo -NoProfile -ExecutionPolicy Bypass -File \"%SCRIPT_DIR%run-worker.ps1\"",
  "set \"EXIT_CODE=%ERRORLEVEL%\"", "echo.",
  "if not \"%EXIT_CODE%\"==\"0\" echo Worker failed with exit code %EXIT_CODE%.",
  "pause", "endlocal & exit /b %EXIT_CODE%", ""
].join("\r\n");
const checkBat = [
  "@echo off", "chcp 65001 >nul", "setlocal", "set \"SCRIPT_DIR=%~dp0\"",
  "\"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe\" -NoLogo -NoProfile -ExecutionPolicy Bypass -File \"%SCRIPT_DIR%run-worker.ps1\" -Mode check",
  "set \"EXIT_CODE=%ERRORLEVEL%\"", "echo.", "pause", "endlocal & exit /b %EXIT_CODE%", ""
].join("\r\n");

// Re-running refreshes only the files owned by this builder; runtime results are never copied or removed.
await fs.access(nodeSource);
await fs.access(path.join(browserSource, "chrome-win64/chrome.exe"));
await fs.mkdir(outputRoot, { recursive: true });

async function sha256(file) {
  const hash = crypto.createHash("sha256");
  const handle = await fs.open(file, "r");
  try {
    for await (const chunk of handle.createReadStream()) hash.update(chunk);
  } finally { await handle.close(); }
  return hash.digest("hex");
}

async function copyFileIfMissing(source, target) {
  try { await fs.access(target); }
  catch { await fs.copyFile(source, target); }
}

async function copyDirectoryIfMissing(source, target) {
  try { await fs.access(target); }
  catch { await fs.cp(source, target, { recursive: true }); }
}

async function walk(dir, base = dir) {
  const files = [];
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...await walk(full, base));
    else files.push({ full, relative: path.relative(base, full).replaceAll("\\", "/") });
  }
  return files;
}

const summaries = [];
for (let device = 1; device <= 5; device += 1) {
  const number = String(device).padStart(2, "0");
  const name = `设备${number}_百度资讯便携工作节点`;
  const target = path.join(outputRoot, name);
  const taskName = `设备${number}_百度资讯检索词任务.json`;
  const taskSource = path.join(taskRoot, taskName);
  const taskData = JSON.parse(await fs.readFile(taskSource, "utf8"));
  const taskCount = Number(taskData.taskCount ?? taskData.keywords?.length ?? 0);
  const topic2TaskName = `设备${number}_专题二_百度资讯检索词任务.json`;
  const topic2TaskSource = path.join(topic2TaskRoot, topic2TaskName);
  const topic2TaskData = JSON.parse(await fs.readFile(topic2TaskSource, "utf8"));
  const topic2TaskCount = Number(topic2TaskData.taskCount ?? topic2TaskData.keywords?.length ?? 0);
  const queueName = "task-queue.json";
  const queue = {
    schemaVersion: "1.0",
    workerId: `worker-${number}`,
    executionMode: "sequential",
    tasks: [
      { name: "专题一：全国地产设计产品力监测", taskFile: `tasks/${taskName}`, outputDir: "runs/current", stateDir: ".state/current", transitionDelaySeconds: 300 },
      { name: "专题二：北京臻澐项目口碑", taskFile: `tasks/${topic2TaskName}`, outputDir: "runs/topic2-current", stateDir: ".state/topic2-current", transitionDelaySeconds: 0 }
    ]
  };
  console.log(`[${device}/5] 构建设备${number}，专题一 ${taskCount} 条，专题二 ${topic2TaskCount} 条`);
  await fs.mkdir(path.join(target, "runtime/node"), { recursive: true });
  await fs.mkdir(path.join(target, "tasks"), { recursive: true });
  await fs.mkdir(path.join(target, "runs"), { recursive: true });
  await fs.mkdir(path.join(target, ".state"), { recursive: true });
  await fs.rm(path.join(target, "tasks", "任务队列.json"), { force: true });
  await Promise.all([
    copyFileIfMissing(nodeSource, path.join(target, "runtime/node/node.exe")),
    copyDirectoryIfMissing(browserSource, path.join(target, "runtime/browsers")),
    copyDirectoryIfMissing(path.join(root, "node_modules"), path.join(target, "node_modules")),
    fs.cp(path.join(root, "src"), path.join(target, "src"), { recursive: true }),
    fs.copyFile(taskSource, path.join(target, "tasks", taskName)),
    fs.copyFile(topic2TaskSource, path.join(target, "tasks", topic2TaskName)),
    fs.writeFile(path.join(target, "tasks", queueName), `${JSON.stringify(queue, null, 2)}\n`, "utf8"),
    fs.copyFile(path.join(root, "package.json"), path.join(target, "package.json")),
    fs.copyFile(path.join(root, "package-lock.json"), path.join(target, "package-lock.json")),
    fs.copyFile(path.join(root, "run-worker.ps1"), path.join(target, "run-worker.ps1")),
    fs.writeFile(path.join(target, "启动工作节点.bat"), launchBat, "ascii"),
    fs.writeFile(path.join(target, "检查运行环境.bat"), checkBat, "ascii"),
    fs.copyFile(path.join(root, "README_工作节点.txt"), path.join(target, "README_工作节点.txt")),
    fs.writeFile(path.join(target, "VERSION"), `${version}\n`)
  ]);
  const inventory = (await walk(target)).filter((file) => file.relative !== "manifest.json" && !file.relative.startsWith("runs/") && !file.relative.startsWith(".state/"));
  const files = [];
  for (const file of inventory) {
    const stat = await fs.stat(file.full);
    files.push({ path: file.relative, size: stat.size, sha256: await sha256(file.full) });
  }
  const manifest = {
    schemaVersion: "1.1", version, workerId: `worker-${number}`, deviceNumber: device,
    taskFiles: [`tasks/${taskName}`, `tasks/${topic2TaskName}`], taskQueueFile: `tasks/${queueName}`,
    topic1TaskCount: taskCount, topic2TaskCount, taskCount: taskCount + topic2TaskCount, createdAt: new Date().toISOString(),
    targetPlatform: "win32-x64", nodeVersion: "v24.19.0", playwrightVersion: "1.63.0",
    browser: "Chrome for Testing 153.0.8010.12", containsCredentials: false,
    excluded: ["历史 runs", "历史 .state/browser-profile", "Cookie", "Excel锁文件", "开发测试数据", "数据库凭据"],
    files
  };
  await fs.writeFile(path.join(target, "manifest.json"), JSON.stringify(manifest, null, 2));
  const bytes = (await walk(target)).reduce((sum, file) => sum + 0, 0);
  summaries.push({ workerId: manifest.workerId, directory: name, topic1TaskCount: taskCount, topic2TaskCount, taskCount: taskCount + topic2TaskCount, fileCount: files.length + 1 });
}
await fs.writeFile(path.join(outputRoot, "部署包总清单.json"), JSON.stringify({ version, workerCount: 5, totalTasks: summaries.reduce((sum, item) => sum + item.taskCount, 0), workers: summaries }, null, 2));
console.log(JSON.stringify({ outputRoot, version, workers: summaries.length, totalTasks: summaries.reduce((sum, item) => sum + item.taskCount, 0) }, null, 2));
