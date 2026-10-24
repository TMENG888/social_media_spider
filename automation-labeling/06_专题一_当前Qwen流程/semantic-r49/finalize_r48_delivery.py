"""Offline r48 delivery bookkeeping; no inference, production or pilot entry point."""
import hashlib
import json
from pathlib import Path

from prepare_regression_delivery import prepare
from validate_delivery import validate

ROOT = Path(__file__).parent
OUT = Path('E:/Codex/outputs/20261022_专题一Qwen回归对照_r48')
RUN = ROOT / 'run_r48'


def main(action):
    if action == 'prepare':
        for batch in 'ABC':
            prepare(batch, 'r48')
        review = {
            'version': 'r48',
            'reviewer_type': 'codex',
            'source_counts': {b: 10 for b in 'ABC'},
            'source_tag_numerical_gate_passed': True,
            'approved_for_pilot': False,
            'critical_errors': None,
            'critical_error_note': '已复核变更对象/否定边界；未完成全部字段零关键错误认证。数值达标不替代语义验收或扩量授权。',
            'scope': '当前只交付参考集回归候选；不启动固定10篇试跑或300篇。',
            'result_sha256': {
                b: hashlib.sha256((RUN / f'{b}_results.json').read_bytes()).hexdigest()
                for b in 'ABC'
            },
            'known_limitations': [
                'C参与过调试，仅为回归集，不是独立留出集。',
                'B/C切片定位标签召回低于80%；用户接受的数值门槛为来源级标签P/R。',
                '仍有粗切片、过细泛述、语义近重复及有效产品配置漏标。',
                '部分证据偏长或截断单位；部分摘要含原文未明确的因果连接。',
                '未宣称全部字段无误，不切换生产默认入口。',
            ],
            'production_activated': False,
            'pilot_started': False,
            'batch300_started': False,
        }
        (RUN / 'semantic_release.json').write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf8')
    elif action == 'validate':
        for batch in 'ABC':
            validate(batch, 'r48', OUT / f'Qwen回归集{batch}_10篇文章.xlsx')
    else:
        raise ValueError(action)


if __name__ == '__main__':
    import sys
    main(sys.argv[1])
