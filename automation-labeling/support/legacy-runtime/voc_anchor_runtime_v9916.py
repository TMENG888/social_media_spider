"""Post-drain adapter: literal recovery, bounded failed-stage repair, no tag acceptance."""
import copy
import time

import voc_batch_v99 as v
from voc_anchor_recovery_candidate_v9916 import candidate, semantics
from voc_runtime_reliability_v9915 import retryable_failure
from structured_response_validation_v58 import issues
from bounded_visible_contract_v60 import contract


def valid_boundary(text, raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('units'), list):
        return False
    return not issues(raw, contract(v.partition.boundary.SCHEMA, {})) and not v.partition.boundary.locate(text, raw)[1]


def same_semantics(before, after):
    return (isinstance(after, dict) and isinstance(after.get('units'), list)
            and len(before['units']) == len(after['units']) and semantics(before) == semantics(after)
            and {k: val for k, val in before.items() if k != 'units'} ==
                {k: val for k, val in after.items() if k != 'units'})


def transport_runner_class(base, stop, sleep=time.sleep):
    class BoundedTransportRunner(base):
        def call(self, system, payload, doc, phase, response_schema=None):
            history = []
            for batch in range(3):
                if batch:
                    for _ in range(20 * batch):
                        if stop() or self.fatal.is_set():
                            return raw, metric
                        sleep(.1)
                raw, metric = super().call(system, payload, doc, phase, response_schema)
                if raw is not None or not retryable_failure(metric) or stop() or self.fatal.is_set():
                    break
                history.append({'request_key': metric['request_key'], 'status': metric['status'],
                                'attempts': len(metric.get('attempts') or [])})
            if history:
                metric = dict(metric, v9916_transport_batches=history,
                    accounting='Formal calls/history only; this diagnostic list is not additional usage')
            return raw, metric
    return BoundedTransportRunner


def anchor_runner_class(base):
    class AnchorRuntimeRunner(base):
        def call(self, system, payload, doc, phase, response_schema=None):
            raw, metric = super().call(system, payload, doc, phase, response_schema)
            if raw is None or not phase.startswith('Reduce全文语义边界'):
                return raw, metric
            original = copy.deepcopy(raw)
            fixed, proof = candidate(doc['text'], raw)
            evidence = {'record_id': doc['record_id'], 'phase': phase,
                        'original_request_key': metric['request_key'], 'literal_recovery': proof,
                        'not_tag_acceptance': True, 'independent_semantic_review_required': True}
            if proof['prepared']:
                evidence['recovered_response'] = fixed
            elif not valid_boundary(doc['text'], raw):
                # The original HTTP response remains successful in its formal ledger.
                # This is one new missing-stage correction, never a cache deletion or
                # resubmission of the successful original request.
                correction = {'source_text': doc['text'], 'original_payload': payload,
                              'invalid_boundary_response': original,
                              'location_failure': proof.get('reason'),
                              'task': '仅修复逐字起点引文或出现序号；不得新增删并切片或修改其它字段。'}
                repaired, repair_metric = super().call(system +
                    '\n本次是失败定位阶段的纠错。每条start_quote必须逐字存在于source_text，20至35字符；'
                    '逐字照抄，不省略非空白字。保持全部切片数量、对象、主题、理由、置信度、疑点及其它字段原值。'
                    '正确定位不等于语义正确，不提高置信度或清除疑点。',
                    correction, doc, phase + '-缺失定位阶段纠错-v9916', response_schema)
                evidence['correction_metric'] = repair_metric
                if repaired is not None and same_semantics(original, repaired):
                    repaired, repair_proof = candidate(doc['text'], repaired)
                    evidence['correction_literal_recovery'] = repair_proof
                    if valid_boundary(doc['text'], repaired):
                        fixed = repaired
                        evidence['recovered_response'] = fixed
                    else:
                        evidence['correction_rejected'] = 'Still not exact/unique source locations'
                else:
                    evidence['correction_rejected'] = 'Missing response or changed semantic fields; original retained'
            if evidence.get('recovered_response') is not None or evidence.get('correction_metric'):
                v.save('control/anchor_fast_recovery_v9916/location_audit/' +
                    v.b.digest([doc['record_id'], phase, metric['request_key']]) + '.json', evidence)
                metric = dict(metric, v9916_location_recovery=evidence)
            return fixed, metric
    return AnchorRuntimeRunner
