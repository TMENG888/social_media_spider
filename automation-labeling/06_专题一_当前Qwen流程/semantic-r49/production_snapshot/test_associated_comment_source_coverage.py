import unittest
import verify_original_csv_sources as v


class Index:
    def map_comment(self,row):
        return ({'id':row['parent']} if row.get('parent') else None),'test-only'


class CommentCoverage(unittest.TestCase):
    def test_comment_project_does_not_hide_associated_row(self):
        comments=[{'id':'C1','parent':'P1','项目':'其他专题'},
                  {'id':'C2','parent':'P1','项目':None}]
        self.assertEqual({'C1','C2'},v.associated_comment_ids(comments,Index(),{'P1'}))
    def test_unrelated_parent_not_added(self):
        self.assertEqual(set(),v.associated_comment_ids([{'id':'C1','parent':'P2'}],Index(),{'P1'}))
    def test_conflicting_or_missing_parent_not_arbitrarily_selected(self):
        self.assertEqual(set(),v.associated_comment_ids([{'id':'C1','parent':None}],Index(),{'P1'}))


if __name__=='__main__':unittest.main()
