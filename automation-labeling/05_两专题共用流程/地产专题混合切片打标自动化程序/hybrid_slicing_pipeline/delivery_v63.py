"""Independent comment relation checks and dictionary-aware product scope."""
import delivery_v62 as current
import project_relation_check_v63 as relations
import article_scope_v63 as article_scope

VERSION = 'delivery-v11.63-independent-comment-relation-dictionary-scope-20261010'
pipeline = current.current.current.integrated
_projects = pipeline.identity.review_projects
_exclusion = current.current.current.check_exclusion


def review_projects(comment, parent, projects, doc, runner):
    targets, calls, audit, errors = _projects(comment, parent, projects, doc, runner)
    kept, cc, aa, ee = relations.review(comment, parent, targets, doc, runner)
    return kept, calls+cc, audit+[{'independent_relation_check': aa}], errors+ee


def check_exclusion(doc, unit, segments, runner):
    if doc['kind'] == '文章' and doc['topic'] == pipeline.previous.p.base.T1:
        return article_scope.review(doc, unit, segments, runner, pipeline.previous)
    return _exclusion(doc, unit, segments, runner)


def activate():
    current.activate()
    relations.bounded = current.current.current.visible.review
    article_scope.bounded = current.current.current.visible.review
    pipeline.identity.review_projects = review_projects
    pipeline.previous.check_exclusion = check_exclusion
    pipeline.previous.VERSION = VERSION
    pipeline.previous.IMPLEMENTATION_FILES = list(dict.fromkeys(
        pipeline.previous.IMPLEMENTATION_FILES + ['delivery_v63.py','project_relation_check_v63.py','article_scope_v63.py']))


if __name__ == '__main__':
    activate()
    pipeline.previous.main()
