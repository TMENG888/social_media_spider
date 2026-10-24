"""Bind completed Codex regression review to exact candidate outputs; never execute batch."""
import hashlib
import json
from pathlib import Path
import version_contract

ROOT = Path(__file__).parent
RUN = ROOT / 'run_r49'


def main():
    assert version_contract.verify_frozen()['version'] == 'r49'
    reviews = ['semantic_review_AB_r49.md', 'semantic_review_C_r49.md']
    record = {
        'version': 'r49', 'reviewer_type': 'codex',
        'source_counts': {}, 'reviewed_label_instances': {},
        'source_tag_numerical_gate_passed': True,
        'approved_for_pilot': False,
        'critical_errors': 0,
        'critical_error_scope': '当前ABC逐片核验所观察到的标签项目/空间对象错配及否定误标；不宣称所有字段零误差或新数据零错误。',
        'scope': '用户当前阶段是参考集回归；尚未确认进入固定10篇扩量，不运行300篇。',
        'result_sha256': {},
        'semantic_review_sha256': {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in reviews},
        'known_limitations': [
            'C参与过调整，仅为回归集，不是独立留出集。',
            '残留漏标、标签口径差异、粗切片、近义重复及未交付配置。',
            'B/C定位标签召回低于80%，通过的是来源级标签门槛。',
            '有限词表词界检查为0不表示任意中文引文完整、最短；仍有长证据。',
            '部分摘要有未明示因果连接、ASR词语规范化及状态限定不足。',
        ],
        'production_activated': False, 'pilot_started': False, 'batch300_started': False,
    }
    for batch in 'ABC':
        path = RUN / f'{batch}_results.json'
        results = json.loads(path.read_text(encoding='utf8'))
        evaluation = json.loads((RUN / f'evaluation_{batch}.json').read_text(encoding='utf8'))
        assert len(results) == 10 and all(r['complete'] for r in results)
        assert evaluation['source_tag']['precision'] >= .8 and evaluation['source_tag']['recall'] >= .8
        record['source_counts'][batch] = len(results)
        record['reviewed_label_instances'][batch] = sum(len(p['labels']) for r in results for p in r['semantic_partition'])
        record['result_sha256'][batch] = hashlib.sha256(path.read_bytes()).hexdigest()
    (RUN / 'semantic_release.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'version': 'r49', 'source_counts': record['source_counts'],
                      'label_instances': record['reviewed_label_instances'],
                      'approved_for_pilot': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
