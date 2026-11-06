import hashlib

def eligible_event(event,current,config):
    identity=(event.get('platform'),event.get('machine'),event.get('workerId'))
    allowed={(n['platform'],n['computer'],n['worker']):n['label'] for n in config['nodes']}
    if identity not in allowed or event.get('kind') not in ('login','captcha'):return False
    if event.get('startedAt',0)<config['sinceMs']:return False
    return bool(current and current.get('incidentId')==event.get('incidentId') and current.get('status')==event.get('status'))

def current_field(event):
    return hashlib.sha256('|'.join([event['platform'],event['machine'],event['workerId']]).encode()).hexdigest()

def auto_payload(event,config):
    node=next(n for n in config['nodes'] if (n['platform'],n['computer'],n['worker'])==(event['platform'],event['machine'],event['workerId']))
    resolved=event.get('status')=='resolved'
    state='登录或验证码已通过自动核验' if resolved else ('登录凭证已失效，请在此机器重新登录' if event['kind']=='login' else '出现验证码，请在此机器人工完成验证')
    text=f"机器：{node['label']} / {event['machine']}\n平台：{event['platform']} / {event['workerId']}\n关键词：{event.get('keyword') or '当前节点'}\n状态：{state}\n"
    text+=('无需重复操作；采集是否已推进以实际运行记录为准。' if resolved else '在浏览器完成后保留页面，程序持续核验，通过后自动续采，无需回车或CONFIRM。请勿清Cookie或重置任务。')
    text+='\n事件：'+event['incidentId']
    return {'msg_type':'interactive','card':{'header':{'template':'green' if resolved else 'orange','title':{'tag':'plain_text','content':node['label']+' '+event['platform']+('：人工处理已核验' if resolved else '：需要人工登录或验证')}},'elements':[{'tag':'div','text':{'tag':'plain_text','content':text}}]}}
