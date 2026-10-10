function redisHandled(item) {
  return Boolean(item.redisConfirmed || item.redisReleased || item.redisFailedHandled);
}

function isFailure(item) {
  return Boolean(item.status && item.status !== "completed" && !item.skipped);
}

export function summarizeWorkerTasks(tasks) {
  const attempts = Array.isArray(tasks) ? tasks : [];
  const latestTasks = [...new Map(attempts.map(item => [
    item.taskId || `${item.topic || ""}/${item.keyword || ""}`,
    item
  ])).values()];
  return {
    completedCount: latestTasks.filter(item => item.status === "completed" || item.skipped).length,
    failedCount: latestTasks.filter(item => isFailure(item) && !redisHandled(item)).length,
    releasedCount: latestTasks.filter(item => item.redisReleased).length,
    retryQueuedCount: latestTasks.filter(item => item.redisFailedHandled).length,
    failedAttemptCount: attempts.filter(isFailure).length,
    unhandledFailedAttemptCount: attempts.filter(item => isFailure(item) && !redisHandled(item)).length,
    releasedAttemptCount: attempts.filter(item => item.redisReleased).length,
    retryQueuedAttemptCount: attempts.filter(item => item.redisFailedHandled).length
  };
}
