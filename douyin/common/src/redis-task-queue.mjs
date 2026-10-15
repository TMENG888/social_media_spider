import { randomUUID } from "node:crypto";
import { maySkipExhausted } from "./retry-disposition.mjs";

// All keys are explicit and share a Redis Cluster hash tag. Never construct keys in Lua.
const KEY_NAMES = ["payloads", "statuses", "attempts", "tokens", "owners", "pending", "leases", "results", "errors", "failed", "deferrals"];
const PRELUDE = `
if redis.replicate_commands then redis.replicate_commands() end
local function now_ms()
  local value = redis.call('TIME')
  return tonumber(value[1]) * 1000 + math.floor(tonumber(value[2]) / 1000)
end
local function check_lease(id, token, now)
  local expiry = tonumber(redis.call('ZSCORE', KEYS[7], id))
  return redis.call('HGET', KEYS[2], id) == 'leased'
    and redis.call('HGET', KEYS[4], id) == token
    and expiry and expiry > now
end
local function clear_lease(id)
  redis.call('HDEL', KEYS[4], id)
  redis.call('HDEL', KEYS[5], id)
  redis.call('ZREM', KEYS[7], id)
end
local function retry_or_fail(id, now, max_attempts, retry_delay, reason)
  local attempt = tonumber(redis.call('HGET', KEYS[3], id)) or 0
  clear_lease(id)
  redis.call('HSET', KEYS[9], id, reason)
  if attempt >= max_attempts then
    redis.call('HSET', KEYS[2], id, 'failed')
    redis.call('ZREM', KEYS[6], id)
    redis.call('ZADD', KEYS[10], now, id)
    return 'failed', 0, attempt
  end
  local retry_at = now + math.min(retry_delay * math.pow(2, math.max(0, attempt - 1)), 3600000)
  redis.call('HSET', KEYS[2], id, 'pending')
  redis.call('ZADD', KEYS[6], retry_at, id)
  return 'pending', retry_at, attempt
end
`;

const PUBLISH = PRELUDE + `
local now = now_ms()
local added = 0
local existing = 0
-- Redis scripts are atomic but do not roll back on error: validate the entire batch first.
local proposed = {}
for index = 1, #ARGV, 3 do
  local id, payload = ARGV[index], ARGV[index + 1]
  if proposed[id] and proposed[id] ~= payload then
    return redis.error_reply('TASK_PAYLOAD_CONFLICT ' .. id)
  end
  proposed[id] = payload
  if redis.call('HEXISTS', KEYS[2], id) == 1 and redis.call('HGET', KEYS[1], id) ~= payload then
    return redis.error_reply('TASK_PAYLOAD_CONFLICT ' .. id)
  end
end
for index = 1, #ARGV, 3 do
  local id = ARGV[index]
  if redis.call('HEXISTS', KEYS[2], id) == 1 then
    existing = existing + 1
  else
    redis.call('HSET', KEYS[1], id, ARGV[index + 1])
    redis.call('HSET', KEYS[2], id, 'pending')
    redis.call('HSET', KEYS[3], id, 0)
    redis.call('ZADD', KEYS[6], tonumber(ARGV[index + 2]), id)
    added = added + 1
  end
end
return cjson.encode({added = added, existing = existing, total = redis.call('HLEN', KEYS[2])})
`;

const CLAIM = PRELUDE + `
local owner, token = ARGV[1], ARGV[2]
local lease_ms, max_attempts, retry_delay = tonumber(ARGV[3]), tonumber(ARGV[4]), tonumber(ARGV[5])
local now = now_ms()
-- Bounded recovery keeps a single claim from monopolizing Redis after a large outage.
local expired = redis.call('ZRANGEBYSCORE', KEYS[7], '-inf', now, 'LIMIT', 0, 1000)
for _, id in ipairs(expired) do
  if redis.call('HGET', KEYS[2], id) == 'leased' then
    retry_or_fail(id, now, max_attempts, retry_delay,
      cjson.encode({message = 'Lease expired before confirmation', code = 'LEASE_EXPIRED', at = now}))
  else
    clear_lease(id)
  end
end
while true do
  local next_ids
  if ARGV[6] and ARGV[6] ~= '' then
    local ready_at = tonumber(redis.call('ZSCORE', KEYS[6], ARGV[6]))
    next_ids = ready_at and ready_at <= now and {ARGV[6]} or {}
  else
    next_ids = redis.call('ZRANGEBYSCORE', KEYS[6], '-inf', now, 'LIMIT', 0, 1)
  end
  if #next_ids == 0 then return false end
  local id = next_ids[1]
  redis.call('ZREM', KEYS[6], id)
  if redis.call('HGET', KEYS[2], id) == 'pending' then
    local payload = redis.call('HGET', KEYS[1], id)
    local previous = tonumber(redis.call('HGET', KEYS[3], id)) or 0
    if not payload or previous >= max_attempts then
      redis.call('HSET', KEYS[2], id, 'failed')
      redis.call('ZADD', KEYS[10], now, id)
      redis.call('HSET', KEYS[9], id, cjson.encode({message = 'Missing task payload or attempt limit reached', code = 'INVALID_PENDING_TASK', at = now}))
    else
      local attempt = redis.call('HINCRBY', KEYS[3], id, 1)
      local expiry = now + lease_ms
      redis.call('HSET', KEYS[2], id, 'leased')
      redis.call('HSET', KEYS[4], id, token)
      redis.call('HSET', KEYS[5], id, owner)
      redis.call('ZADD', KEYS[7], expiry, id)
      return cjson.encode({taskId = id, payload = payload, token = token, leaseMs = lease_ms, leaseUntil = expiry, attempt = attempt})
    end
  end
end
`;

const RENEW = PRELUDE + `
local id, token, lease_ms = ARGV[1], ARGV[2], tonumber(ARGV[3])
local now = now_ms()
if not check_lease(id, token, now) then return redis.error_reply('LEASE_LOST') end
local expiry = now + lease_ms
redis.call('ZADD', KEYS[7], expiry, id)
return cjson.encode({taskId = id, leaseUntil = expiry, leaseMs = lease_ms})
`;

const ASSERT_LEASE = PRELUDE + `
local id, token = ARGV[1], ARGV[2]
local now = now_ms()
if not check_lease(id, token, now) then return redis.error_reply('LEASE_LOST') end
return cjson.encode({taskId = id, leaseUntil = tonumber(redis.call('ZSCORE', KEYS[7], id)), serverTime = now})
`;

const COMPLETE = PRELUDE + `
local id, token = ARGV[1], ARGV[2]
local now = now_ms()
if not check_lease(id, token, now) then return redis.error_reply('LEASE_LOST') end
local result=cjson.decode(ARGV[3])
if type(result)=='table' and result.disposition=='no_change' then
 local e=result.noChangeEvidence
 if result.status~='completed_with_skips' or result.accepted~=false or type(e)~='table'
  or type(e.beforeDigest)~='string' or #e.beforeDigest~=64 or e.beforeDigest~=e.afterDigest
  or e.importOk~=true or e.freshSearch~=true or e.accepted~=false then
  return redis.error_reply('INVALID_NO_CHANGE_EVIDENCE')
 end
end
local status=type(result)=='table' and result.status=='completed_with_skips' and 'completed_with_skips' or 'completed'
clear_lease(id)
redis.call('ZREM', KEYS[6], id)
redis.call('ZREM', KEYS[10], id)
redis.call('HDEL', KEYS[9], id)
redis.call('HSET', KEYS[2], id, status)
redis.call('HSET', KEYS[8], id, ARGV[3])
return cjson.encode({taskId = id, status = status, completedAt = now})
`;

const FAIL = PRELUDE + `
local id, token = ARGV[1], ARGV[2]
local now = now_ms()
if not check_lease(id, token, now) then return redis.error_reply('LEASE_LOST') end
local status, retry_at, attempt = retry_or_fail(id, now, tonumber(ARGV[4]), tonumber(ARGV[5]), ARGV[3])
if status=='failed' and ARGV[6]=='allow_content_skip' then
  local evidence=cjson.decode(ARGV[7])
  evidence.status='skipped_unresolved'; evidence.accepted=false
  evidence.attempts=attempt; evidence.dispositionAt=now
  evidence.policy='20261013-user-authorized-finite-skip'
  redis.call('HSET',KEYS[8],id,cjson.encode(evidence))
  redis.call('HSET',KEYS[2],id,'skipped_unresolved')
  redis.call('ZREM',KEYS[10],id)
  status='skipped_unresolved'
end
return cjson.encode({taskId = id, status = status, retryAt = retry_at, attempt = attempt})
`;

// Quality exhaustion is a retained failure, not completion or a retry reset.
const PARK = PRELUDE + `
local id, token = ARGV[1], ARGV[2]
local now = now_ms()
if not check_lease(id, token, now) then return redis.error_reply('LEASE_LOST') end
clear_lease(id)
redis.call('ZREM', KEYS[6], id)
redis.call('HSET', KEYS[2], id, 'failed')
redis.call('HSET', KEYS[8], id, ARGV[3])
redis.call('HSET', KEYS[9], id, ARGV[4])
redis.call('ZADD', KEYS[10], now, id)
return cjson.encode({taskId=id,status='failed',requiresReview=true,attempt=tonumber(redis.call('HGET',KEYS[3],id)) or 0})
`;

const RELEASE = PRELUDE + `
local id, token = ARGV[1], ARGV[2]
local now = now_ms()
if not check_lease(id, token, now) then return redis.error_reply('LEASE_LOST') end
clear_lease(id)
-- A cooperative stop is not a failed attempt; repeated user stops must not exhaust retries.
local attempt = math.max(0, (tonumber(redis.call('HGET', KEYS[3], id)) or 1) - 1)
local payload = redis.call('HGET', KEYS[1], id)
local decoded = payload and cjson.decode(payload) or {}
local priority = tonumber(decoded.sequence) or now
redis.call('HSET', KEYS[3], id, attempt)
redis.call('HSET', KEYS[2], id, 'pending')
redis.call('ZADD', KEYS[6], priority, id)
return cjson.encode({taskId = id, status = 'pending', releasedAt = now, attempt = attempt})
`;

const STATS = PRELUDE + `
local now = now_ms()
local counts = {pending = 0, leased = 0, completed = 0, completed_with_skips = 0, skipped_unresolved = 0, failed = 0, total = 0}
for _, status in ipairs(redis.call('HVALS', KEYS[2])) do
  counts.total = counts.total + 1
  if counts[status] ~= nil then counts[status] = counts[status] + 1 end
end
local failed = {}
local failures = redis.call('ZRANGE', KEYS[10], 0, -1, 'WITHSCORES')
for index = 1, #failures, 2 do
  local id = failures[index]
  table.insert(failed, {taskId = id, payload = redis.call('HGET', KEYS[1], id) or 'null',
    attempt = tonumber(redis.call('HGET', KEYS[3], id)) or 0,
    errorPayload = redis.call('HGET', KEYS[9], id) or 'null', failedAt = tonumber(failures[index + 1])})
end
return cjson.encode({counts = counts, failed = failed, serverTime = now,
  ready = redis.call('ZCOUNT', KEYS[6], '-inf', now),
  expiredLeases = redis.call('ZCOUNT', KEYS[7], '-inf', now)})
`;

// A transient node/import failure is not a content attempt, but it cannot be
// released forever with a rolled-back counter. This budget is cross-machine.
const DEFER = PRELUDE + `
local id, token = ARGV[1], ARGV[2]
local now = now_ms()
if not check_lease(id,token,now) then return redis.error_reply('LEASE_LOST') end
local evidence=cjson.decode(ARGV[3])
if type(evidence)~='table' then return redis.error_reply('INVALID_DEFER_EVIDENCE') end
local count=redis.call('HINCRBY',KEYS[11],id,1)
local attempt=math.max(0,(tonumber(redis.call('HGET',KEYS[3],id)) or 1)-1)
clear_lease(id)
redis.call('HSET',KEYS[3],id,attempt)
evidence.deferrals=count; evidence.requiresAction=count>=3; evidence.accepted=false
redis.call('HSET',KEYS[8],id,cjson.encode(evidence))
redis.call('HSET',KEYS[9],id,cjson.encode({message=evidence.error or 'NODE_OR_IMPORT_DEFERRED',code='BOUNDED_DEFER',deferrals=count,at=now}))
local status=count>=3 and 'failed' or 'pending'
redis.call('HSET',KEYS[2],id,status)
redis.call('ZREM',KEYS[6],id)
if status=='failed' then redis.call('ZADD',KEYS[10],now,id)
else redis.call('ZADD',KEYS[6],now+math.max(1000,tonumber(ARGV[4]))*math.pow(2,count-1),id) end
return cjson.encode({taskId=id,status=status,deferrals=count,attempt=attempt,requiresAction=count>=3})
`;

export class LeaseLostError extends Error {
  constructor(taskId, cause) {
    super(`Redis task lease no longer belongs to this worker: ${taskId}`, { cause });
    this.name = "LeaseLostError";
    this.code = "LEASE_LOST";
    this.taskId = taskId;
  }
}

export class TaskPayloadConflictError extends Error {
  constructor(taskId, cause) {
    super(`Redis task already has a different payload: ${taskId}`, { cause });
    this.name = "TaskPayloadConflictError";
    this.code = "TASK_PAYLOAD_CONFLICT";
    this.taskId = taskId;
  }
}

function positiveInteger(value, name, allowZero = false) {
  if (!Number.isSafeInteger(value) || value < (allowZero ? 0 : 1)) throw new TypeError(`${name} must be a ${allowZero ? "nonnegative" : "positive"} integer`);
  return value;
}

function identity(value, name) {
  if (value == null || !String(value).trim() || String(value).length > 512 || /[\x00-\x1f]/u.test(String(value))) {
    throw new TypeError(`${name} must be a nonempty identifier of at most 512 characters`);
  }
  return String(value);
}

function jsonPayload(value, name) {
  const serialized = JSON.stringify(value);
  if (serialized === undefined) throw new TypeError(`${name} must be JSON serializable`);
  const canonical = (item) => {
    if (Array.isArray(item)) return item.map(canonical);
    if (item && typeof item === "object") return Object.fromEntries(Object.keys(item).sort().map((key) => [key, canonical(item[key])]));
    return item;
  };
  return JSON.stringify(canonical(JSON.parse(serialized)));
}

/** A node-redis client must be connected by the caller; credentials never enter this module. */
export class RedisTaskQueue {
  async defer(taskId,token,result={}) {
    return this.evaluate(DEFER,[identity(taskId,'taskId'),identity(token,'token'),jsonPayload(result,'result'),String(this.retryDelayMs)],taskId);
  }
  constructor({ client, prefix = "xhs:douyin", campaign, leaseMs = 300000, maxAttempts = 3, retryDelayMs = 60000 } = {}) {
    if (!client || typeof client.eval !== "function") throw new TypeError("A connected node-redis client is required");
    if (!/^xhs(?::[A-Za-z0-9_-]+)*$/u.test(prefix)) throw new TypeError("prefix must stay inside the xhs namespace");
    const tag = identity(campaign, "campaign");
    if (/[{}\s]/u.test(tag)) throw new TypeError("campaign must not contain braces or whitespace");
    this.client = client;
    this.namespace = `${prefix}:{${tag}}`;
    this.keys = KEY_NAMES.map((name) => `${this.namespace}:${name}`);
    this.leaseMs = positiveInteger(leaseMs, "leaseMs");
    this.maxAttempts = positiveInteger(maxAttempts, "maxAttempts");
    this.retryDelayMs = positiveInteger(retryDelayMs, "retryDelayMs", true);
  }

  async evaluate(script, arguments_ = [], taskId = null) {
    try {
      const raw = await this.client.eval(script, { keys: this.keys, arguments: arguments_.map(String) });
      return raw == null || raw === false ? null : JSON.parse(raw);
    } catch (error) {
      if (/\bLEASE_LOST\b/u.test(String(error.message || error))) throw new LeaseLostError(taskId, error);
      const conflict = String(error.message || error).match(/\bTASK_PAYLOAD_CONFLICT (.+)$/u);
      if (conflict) throw new TaskPayloadConflictError(conflict[1], error);
      throw error;
    }
  }

  async publish(tasks) {
    if (!Array.isArray(tasks)) throw new TypeError("tasks must be an array");
    const arguments_ = tasks.flatMap((task, index) => {
      if (!task || typeof task !== "object" || Array.isArray(task)) throw new TypeError("Each task must be an object");
      const priority = task.sequence == null ? index + 1 : Number(task.sequence);
      if (!Number.isSafeInteger(priority) || priority < 1) throw new TypeError("task.sequence must be a positive integer");
      return [identity(task.redisTaskId ?? task.id, "taskId"), jsonPayload(task, "task"), priority];
    });
    return this.evaluate(PUBLISH, arguments_);
  }

  async claim(workerId, taskId = null) {
    const claimed = await this.evaluate(CLAIM, [identity(workerId, "workerId"), randomUUID(), this.leaseMs, this.maxAttempts, this.retryDelayMs,taskId==null?'':identity(taskId,'taskId')]);
    if (!claimed) return null;
    const { payload, ...lease } = claimed;
    return { ...lease, task: JSON.parse(payload) };
  }

  async inspect(taskId) {
    const result=await this.evaluate(`local id=ARGV[1]; return cjson.encode({taskId=id,status=redis.call('HGET',KEYS[2],id) or 'missing',attempts=tonumber(redis.call('HGET',KEYS[3],id)) or 0,owner=redis.call('HGET',KEYS[5],id) or cjson.null,leaseUntil=tonumber(redis.call('ZSCORE',KEYS[7],id)),result=redis.call('HGET',KEYS[8],id) or cjson.null,error=redis.call('HGET',KEYS[9],id) or cjson.null})`,[identity(taskId,'taskId')]);
    for(const key of ['result','error'])if(typeof result[key]==='string'){try{result[key]=JSON.parse(result[key]);}catch{}}
    return result;
  }

  renew(taskId, token) {
    return this.evaluate(RENEW, [identity(taskId, "taskId"), identity(token, "token"), this.leaseMs], taskId);
  }

  verifyExisting(task) {
    const id=identity(task.redisTaskId??task.id,'taskId');
    return this.evaluate(`local id=ARGV[1]; if redis.call('HEXISTS',KEYS[2],id)==0 then return redis.error_reply('SELECTED_TASK_UNAVAILABLE') end; if redis.call('HGET',KEYS[1],id)~=ARGV[2] then return redis.error_reply('TASK_PAYLOAD_CONFLICT '..id) end; return cjson.encode({added=0,existing=1,total=redis.call('HLEN',KEYS[2])})`,[id,jsonPayload(task,'task')]);
  }

  assertLease(taskId, token) {
    return this.evaluate(ASSERT_LEASE, [identity(taskId, "taskId"), identity(token, "token")], taskId);
  }

  complete(taskId, token, result = null) {
    return this.evaluate(COMPLETE, [identity(taskId, "taskId"), identity(token, "token"), jsonPayload(result ?? null, "result")], taskId);
  }

  fail(taskId, token, error, result = null) {
    const message = error instanceof Error
      ? { name: error.name, message: error.message, code: error.code ?? null }
      : { message: String(error ?? "Task failed") };
    return this.evaluate(FAIL, [identity(taskId, "taskId"), identity(token, "token"), JSON.stringify(message), this.maxAttempts, this.retryDelayMs,
      maySkipExhausted(result) ? 'allow_content_skip' : '', jsonPayload(result ?? {}, "result")], taskId);
  }

  release(taskId, token) {
    return this.evaluate(RELEASE, [identity(taskId, "taskId"), identity(token, "token")], taskId);
  }

  park(taskId, token, result) {
    return this.evaluate(PARK,[identity(taskId,"taskId"),identity(token,"token"),jsonPayload(result,"result"),
      JSON.stringify({code:"ASR_REVIEW_REQUIRED",message:result?.error||"字幕质量重试耗尽，需要审核或新修复策略"})],taskId);
  }

  async stats() {
    const result = await this.evaluate(STATS);
    // Redis cjson encodes an empty Lua table as {}; callers always receive an array.
    result.failed = Array.isArray(result.failed) ? result.failed.map(({ payload, errorPayload, ...failure }) =>
      ({ ...failure, task: JSON.parse(payload), error: JSON.parse(errorPayload) })) : [];
    return result;
  }
}

