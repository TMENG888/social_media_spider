"""Typed semantic merge prerequisites; never generates text boundaries/tags."""
SCOPES={'single_floorplan','single_clubhouse','single_solution',
        'single_facility','single_issue','single_property_fact'}


def scope_error(group):
    if group.get('same_object') is not True or group.get('same_topic') is not True:
        return '相邻合并未确认同一具体对象及同一独立主题；同项目不等于同主题'
    if group.get('object_scope') not in SCOPES:
        return '相邻合并对象范围不是一个户型/会所/具体方案/设施/问题/单一属性事实'
    description=group.get('object_description')
    if not isinstance(description,str) or not description.strip():
        return '相邻合并未说明具体对象与主题'
    return None
