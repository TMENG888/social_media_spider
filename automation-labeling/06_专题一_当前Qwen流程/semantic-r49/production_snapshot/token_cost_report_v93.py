"""Current-output-directory usage only, including saved failed attempts."""
import argparse
import json
from collections import defaultdict
from pathlib import Path
from delivery_v4 import save_json, cached_tokens
from multilabel_v2 import calculate_cost


def report(directory):
    records=[]
    for name in ['calls','call_attempt_history']:
        for path in (directory/name).glob('*.json'):
            records.append(json.loads(path.read_text(encoding='utf-8'))['metrics'])
    buckets=defaultdict(list)
    for metric in records:buckets[(metric['topic'],metric['source_type'])].append(metric)
    def total(items):
        usage=[attempt['usage'] for item in items for attempt in item['attempts'] if attempt.get('usage')]
        # Every HTTP/network attempt is kept, even when no usage was returned.
        unknown=sum(not attempt.get('usage') for item in items for attempt in item['attempts'])
        prompt=sum(u.get('prompt_tokens') or 0 for u in usage);completion=sum(u.get('completion_tokens') or 0 for u in usage)
        cached=sum(min(u.get('prompt_tokens') or 0,cached_tokens(u)) for u in usage)
        prices=[calculate_cost(u.get('prompt_tokens'),cached_tokens(u),u.get('completion_tokens')) for u in usage]
        return {'request_records':len(items),'http_or_network_attempts':sum(len(m['attempts']) for m in items),
            'successful_records':sum(m['status']=='success' for m in items),'prompt_tokens':prompt,'cached_input_tokens':cached,
            'uncached_input_tokens':prompt-cached,'completion_tokens':completion,'total_known_tokens':prompt+completion,
            'known_estimated_yuan':sum(p for p in prices if p is not None),
            'attempts_without_usage':unknown,'usage_records_without_applicable_price':sum(p is None for p in prices),
            'usage_records_missing_token_fields':sum(u.get('prompt_tokens') is None or u.get('completion_tokens') is None for u in usage)}
    data_path=directory/'delivery_results.json'
    keyword_only=not records and data_path.exists() and bool(json.loads(data_path.read_text(encoding='utf-8')).get('keyword_supplement_status'))
    if keyword_only:
        data=json.loads(data_path.read_text(encoding='utf-8'))
        for result in data['results']:buckets[(result['document']['topic'],result['document']['kind'])]
    output={'scope':('本轮仅本地关键词规则，无API请求；新增Token和费用为0，不含上轮API费用。' if keyword_only else '本轮独立目录，不含历史目录；含冒烟、失败及重试。缓存读取不重复计费。'),
        'pricing':'沿用程序配置：非缓存输入0.20元/百万Token，缓存输入0.04元/百万Token，输出0.80元/百万Token；输入超过32000无适用价格，估算非服务商账单。',
        'total':total(records),'by_topic_source':[{'topic':topic,'source_type':kind,**total(items)} for (topic,kind),items in sorted(buckets.items())]}
    save_json(directory/'token_cost_summary.json',output)
    return output


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args()
    print(json.dumps(report(a.output_dir),ensure_ascii=False))
