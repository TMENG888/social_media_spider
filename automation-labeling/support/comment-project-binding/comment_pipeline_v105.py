"""Reusable final project-binding step for the established T2 pipeline.

The original slicer/tagger and immutable source checkpoints are retained. Call
process_saved for cached accepted sources, or process_document for new sources.
Never export the legacy result directly when using this entry point.
"""
import copy
from pathlib import Path
import project_priority as q


def configure(output_dir):
    q.OUT = Path(output_dir)
    q.OUT.mkdir(parents=True, exist_ok=True)


def process_saved(source, runner, force_revision=False):
    if source['document']['kind'] != '评论':
        return copy.deepcopy(source), None
    if source.get('unfinished_units'):
        raise ValueError('Finish missing label stages before final project binding')
    if not any(o['views'] for o in source['outcomes'].values()):
        return copy.deepcopy(source), None
    key = q.digest([q.VERSION, source['record_id'], q.digest(source)])
    overlay_file = q.OUT / 'overlays' / (key + '.json')
    revised_file = q.OUT / 'revised_sources' / (key + '.json')
    # Keep successful earlier-revision routes; only explicitly selected failed
    # or semantically disputed identities are sent to the improved policy.
    if not overlay_file.exists() and not force_revision:
        for version in ('comment-project-priority-20261020-v4','comment-project-priority-20261020-v3','comment-project-priority-20261020-v2'):
            legacy_key=q.digest([version,source['record_id'],q.digest(source)])
            legacy_overlay=q.OUT/'overlays'/(legacy_key+'.json')
            legacy_revised=q.OUT/'revised_sources'/(legacy_key+'.json')
            if legacy_overlay.exists() and legacy_revised.exists():
                overlay_file,revised_file=legacy_overlay,legacy_revised
                break
    if overlay_file.exists():
        overlay = q.p.read(overlay_file)
        assert overlay['source_digest'] == q.digest(source)
    else:
        overlay = q.resolve(source, runner)
        overlay['overlay_file'] = str(overlay_file)
        q.save(overlay_file, overlay)
    if revised_file.exists():
        revised = q.p.read(revised_file)
    else:
        revised = q.apply_overlay(source, overlay)
        revised = q.repair_summaries(source, revised, runner)
        q.save(revised_file, revised)
    # Replaying the independent checker is mandatory for both cache hits and
    # new responses; an existing checkpoint alone is not acceptance.
    from verify_and_merge import verify
    check = verify(source, overlay, revised)
    aligned=copy.deepcopy(revised)
    names={x for project in q.PROJECTS for x in [project['name'],*project['aliases']]}
    repairs=[]
    for uid,outcome in aligned['outcomes'].items():
        for view in outcome['views']:
            canonical=q.PM[view['project_id']]['name']
            for label in view['labels']:
                if label['object'] in names and label['object'] != canonical:
                    label['object_previous']=label['object']
                    label['object']=canonical
                    label['project_object_field_repair']={'actor':'program',
                        'rule':'既有对象字段恰为旧项目案名时，与已裁决新项目统一；不修改普通属性对象。'}
                    repairs.append({'unit_id':uid,'tag_id':label['tag_id'],
                                    'before':label['object_previous'],'after':canonical})
    if repairs:
        aligned['project_object_alignment']={'derived_from':q.reference(revised_file),'repairs':repairs}
        revised_file=q.OUT/'aligned_sources'/(key+'.json')
        q.save(revised_file,aligned)
        revised=aligned
        check=verify(source,overlay,revised)
    proof = {'overlay': q.reference(overlay_file), 'revised_source': q.reference(revised_file),
             'verification': check, 'entrypoint': q.reference(__file__)}
    return revised, proof


def process_document(doc, taxonomy, projects, origins, prior, runner):
    """Existing slicing/tagging first, isolated final attribution before export."""
    source = q.p.process(doc, taxonomy, projects, origins, prior, runner)
    if source['state'] == 'retry_required':
        return source, None
    return process_saved(source, runner)
