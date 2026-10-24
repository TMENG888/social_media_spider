"""Losslessly share repeated evidence quotes within a single Excel cell."""
import copy


def pack(view,catalogue):
    evidence={item['source_key']:item['text'] for item in catalogue}
    keys=list(dict.fromkeys(key for tag in view['labels'] for key in tag['attribute_keys']+tag['context_keys']))
    return {'format':'shared-quotes-v1','quotes':{key:evidence[key] for key in keys},
            'labels':[{'tag_id':tag['tag_id'],'project_id':view['project_id'],
                       'project_identity':copy.deepcopy(tag['project_identity']),
                       'attribute_keys':list(tag['attribute_keys']),'context_keys':list(tag['context_keys'])} for tag in view['labels']]}


def unpack(value):
    if isinstance(value,list):return value
    assert set(value)=={'format','quotes','labels'} and value['format']=='shared-quotes-v1'
    used={key for label in value['labels'] for key in label['attribute_keys']+label['context_keys']}
    assert used==set(value['quotes'])
    return [{'tag_id':label['tag_id'],'project_id':label['project_id'],'project_identity':label['project_identity'],
             'attribute_quotes':[value['quotes'][key] for key in label['attribute_keys']],
             'context_quotes':[value['quotes'][key] for key in label['context_keys']]} for label in value['labels']]
