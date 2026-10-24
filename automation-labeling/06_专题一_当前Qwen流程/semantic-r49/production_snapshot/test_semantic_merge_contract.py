import unittest
from semantic_merge_contract import scope_error


class MergeContract(unittest.TestCase):
    def test_project_identity_alone_is_not_merge_permission(self):
        self.assertIsNotNone(scope_error({'same_object':True,'same_topic':True,
            'object_scope':'same_project','object_description':'项目全介绍'}))
    def test_single_floorplan_configuration_and_single_solution(self):
        for scope in ['single_floorplan','single_solution','single_clubhouse']:
            self.assertIsNone(scope_error({'same_object':True,'same_topic':True,
                'object_scope':scope,'object_description':'当前完整具体方案'}))
    def test_flags_require_literal_booleans(self):
        for value in [None,False,1,'true']:
            self.assertIsNotNone(scope_error({'same_object':True,'same_topic':value,
                'object_scope':'single_floorplan','object_description':'户型'}))
    def test_missing_description_not_silent_merge(self):
        self.assertIsNotNone(scope_error({'same_object':True,'same_topic':True,
            'object_scope':'single_facility','object_description':''}))


if __name__=='__main__':unittest.main()
