import unittest
from studies.gemy_zhou.architecture import *
class ArchitectureTests(unittest.TestCase):
 def test_model_never_faked(self):
  with self.assertRaises(MissingAuthenticatedModel):infer_only_with_frozen_model(None,[],'2026')
 def test_future_features(self):self.assertFalse(validate_feature_availability([{'available_at':'2027','observed_until':'2025'}],'2026'))
 def test_children_capped(self):
  x=ParentChildLedger(100);x.parent_fill('p',20)
  with self.assertRaises(ValueError):x.child_fill('c',21)
 def test_idempotent_and_residual(self):
  x=ParentChildLedger(100);x.parent_fill('p',20);self.assertFalse(x.parent_fill('p',20));x.child_fill('c',7);x.cancel_unfilled_parent();self.assertEqual(x.end_session()['open_qty'],13);self.assertEqual(x.canceled_parent,80)
 def test_overnight_not_erased(self):
  x=ParentChildLedger(100);x.parent_fill('p',20);x.override('2026','carry_overnight','recorded human choice');self.assertEqual(x.end_session()['open_qty'],20)
