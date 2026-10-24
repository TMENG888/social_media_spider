import unittest
from duplicate_pair_batches import review_tasks

class PairBatches(unittest.TestCase):
    def test_all_pairs_once_and_only_relevant_units(self):
        pairs=[{'pair_id':i,'unit_a':0,'unit_b':i+1} for i in range(25)]
        units=[{'unit_index':i,'excerpt':str(i)} for i in range(26)]
        tasks=list(review_tasks(pairs,units))
        self.assertEqual([12,12,1],[len(t['pairs']) for t in tasks])
        self.assertEqual(pairs,[p for t in tasks for p in t['pairs']])
        self.assertEqual([0,25],[u['unit_index'] for u in tasks[-1]['units']])

if __name__=='__main__':unittest.main()
