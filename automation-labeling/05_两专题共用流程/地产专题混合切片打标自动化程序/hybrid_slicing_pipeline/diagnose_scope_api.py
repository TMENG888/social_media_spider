"""Small protocol diagnostic; never prints credentials or source datasets."""
import os
import delivery_v11 as p

key=os.environ.get('YS_LLM_API_KEY')
if not key:raise SystemExit('Missing local environment credential')
for prefix in ('','只返回JSON。\n'):
    response=p.p.base.post_json('http://127.0.0.1:3000/v1/chat/completions',
        {'model':'qwen3.7-flash','temperature':.1,'enable_thinking':False,'max_tokens':1200,
              'response_format':{'type':'json_object'},'messages':[
                  {'role':'system','content':prefix+p.SCOPE_SYSTEM},
                  {'role':'user','content':'{"slice_text":"招聘实习生，英语六级优先","topic_type":"全国地产设计产品力监测","source_type":"文章"}'}]},key,timeout=120)
    print('Explicit JSON instruction:',bool(prefix),'HTTP:',response.status_code)
    if response.status_code>=400:
        print(str(response.json()).replace(key,'[redacted]')[:1200])
    else:
        body=response.json()
        print(body['choices'][0]['message']['content'])
        print('usage:',body.get('usage'))
