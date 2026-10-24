import unittest
import structured_response_validation_v58 as v


class SchemaValidation(unittest.TestCase):
    def test_boolean_not_number(self):
        self.assertTrue(v.issues(True,{'type':'number','minimum':0,'maximum':1}))
    def test_nonfinite_number_rejected(self):
        for value in (float('nan'),float('inf')):
            self.assertTrue(v.issues(value,{'type':'number'}))
    def test_valid_null_union(self):
        self.assertFalse(v.issues(None,{'type':['string','null']}))
    def test_missing_nested_field_and_extra_field(self):
        schema={'type':'array','items':{'type':'object','properties':{'quote':{'type':'string','minLength':1}},'required':['quote'],'additionalProperties':False}}
        self.assertEqual(2,len(v.issues([{'invented':'x'}],schema)))
    def test_rejection_and_low_score_are_structurally_valid(self):
        schema={'type':'object','properties':{'approved':{'type':'boolean'},'confidence':{'type':'number','minimum':0,'maximum':1}},'required':['approved','confidence'],'additionalProperties':False}
        self.assertFalse(v.issues({'approved':False,'confidence':.2},schema))
    def test_one_allowed_anyof_branch(self):
        schema={'anyOf':[{'type':'null'},{'type':'object','properties':{'quote':{'type':'string'}},'required':['quote'],'additionalProperties':False}]}
        self.assertFalse(v.issues(None,schema));self.assertFalse(v.issues({'quote':'真实引文'},schema))
        self.assertTrue(v.issues({},schema))


if __name__=='__main__':unittest.main()
