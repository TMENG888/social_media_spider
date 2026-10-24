"""Compact full dictionary plus canonical same-label fact proposals.

All topic definitions remain present. Canonicalization is before independent
binding, not a delivery-row repair or approval of model proposals.
"""
import copy
from prose_speaker_catalog import source_catalog


def payload(text, index, identity_context=''):
    return {'source_text': text, 'source_catalog': source_catalog(text),
            'identity_context': identity_context,
            'all_applicable_labels': [{'choice_key': key,
                'path': [tag.get('l' + str(i)) or None for i in range(1, 6)],
                'emphasis': tag['emphasis'], 'definition': tag['instruction']}
                for key, tag in index.items()]}


def canonicalize(response):
    if not isinstance(response, dict) or not isinstance(response.get('labels'), list):
        return response
    out = copy.deepcopy(response); merged = {}
    for item in out['labels']:
        if not isinstance(item, dict) or not isinstance(item.get('choice_key'), str):
            return response
        key = item['choice_key']
        if key not in merged:
            merged[key] = item; continue
        prior = merged[key]
        for field in ('source_keys', 'object_keys'):
            if not isinstance(prior.get(field), list) or not isinstance(item.get(field), list):
                return response
            prior[field] = list(dict.fromkeys(prior[field] + item[field]))
        if type(prior.get('confidence')) not in (int, float) or type(item.get('confidence')) not in (int, float):
            return response
        prior['confidence'] = min(prior['confidence'], item['confidence'])
        prior['why'] = str(prior.get('why') or '') + '；' + str(item.get('why') or '')
    out['labels'] = list(merged.values())
    return out
