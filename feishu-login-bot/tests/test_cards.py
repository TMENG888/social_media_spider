import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_test_temp=Path(os.environ.get('LOGIN_TEST_TEMP','E:/Codex/temp/feishu-login-bot-tests'))
_test_temp.mkdir(parents=True,exist_ok=True)
import sys,json
from login_bridge import notice_content
rows=[[{'tag':'text','text':'请在手机扫码'}],[{'tag':'img','image_key':'test_image'}]]
for phase in ['waiting_scan','manual_captcha','waiting_sms','sms_send_unconfirmed']:
 c=notice_content('work03 · 抖音',rows,phase)
 assert c['header']['template']=='orange'
 assert c['elements'][1]['img_key']=='test_image'
for phase in ['verified','resumed']:
 assert notice_content('work03 · 抖音',rows,phase)['header']['template']=='green'
old=notice_content('work03 · 抖音',rows,'cancelled','post')
assert old['zh_cn']['content']==rows
assert notice_content('work03 · 抖音',rows,'cancelled')['header']['template']=='grey'
print(json.dumps({'passed':8,'orangeActionCards':True,'greenSuccessCards':True,'legacyMessageEditsPreserved':True}))
