"""Select existing originals without changing task identity or acceptance."""
import json


def scoped_tasks(common, tasks):
    file = common / 'task-scope.json'
    if not file.exists():
        return tasks
    config = json.loads(file.read_text(encoding='utf-8-sig'))
    if config.get('enabled') is False:
        return tasks
    topics = config.get('allowedTopics')
    if (config.get('version') != 1 or not isinstance(topics, list) or not topics
            or any(topic not in ('topic1', 'topic2') for topic in topics)):
        raise RuntimeError('TASK_SCOPE_INVALID')
    selected = [task for task in tasks if task['topic'] in topics]
    if not selected:
        raise RuntimeError('TASK_SCOPE_EMPTY')
    return selected


def read_scoped_new(runtime):
    # Redis Streams delivers in order. Out-of-scope deliveries stay pending:
    # no ACK, execution, completion, retry charge or checkpoint deletion.
    args, api = runtime.args, runtime.api
    allowed = {task['task_id'] for task in runtime.selected}
    for _ in range(len(runtime.messages) + 1):
        message = api.read_new(args.redis_url, args.redis_password,
                               args.stream, args.group, args.consumer, 1)
        if not message:
            return None
        mid, task = message
        if runtime.messages.get(task['task_id']) != (mid, task):
            raise RuntimeError('VOLUME_OFFICIAL_DELIVERY_MISMATCH')
        if task['task_id'] in allowed:
            return message
        print(json.dumps({'event': 'topic_scope_delivery_retained',
                          'taskId': task['task_id'], 'topic': task['topic'],
                          'executed': False, 'acknowledged': False}), flush=True)
    raise RuntimeError('TASK_SCOPE_DELIVERY_BOUND_EXCEEDED')
