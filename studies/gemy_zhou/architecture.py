"""Architecture invariants only. Never invent the missing authenticated model."""
from dataclasses import dataclass,field
class MissingAuthenticatedModel(RuntimeError):pass

def validate_feature_availability(features,decision_at):
    return all(f['available_at']<=decision_at and f['observed_until']<=decision_at for f in features)

def infer_only_with_frozen_model(artifact,features,decision_at):
    if not artifact or not artifact.get('authenticated_original') or not artifact.get('sha256'):
        raise MissingAuthenticatedModel('missing-authenticated-model; no fallback prediction')
    if not validate_feature_availability(features,decision_at):raise ValueError('future feature')
    # A hash alone is not executable weights or permission to guess a network.
    raise MissingAuthenticatedModel('validated metadata does not supply authenticated executable inference')

@dataclass
class ParentChildLedger:
    requested_parent:int
    filled_parent:int=0
    closed_children:int=0
    canceled_parent:int=0
    event_ids:set=field(default_factory=set)
    manual_overrides:list=field(default_factory=list)
    def parent_fill(self,event_id,qty):
        if event_id in self.event_ids:return False
        if qty<=0 or self.filled_parent+self.canceled_parent+qty>self.requested_parent:raise ValueError('parent overfill')
        self.event_ids.add(event_id);self.filled_parent+=qty;return True
    def child_fill(self,event_id,qty):
        if event_id in self.event_ids:return False
        if qty<=0 or self.closed_children+qty>self.filled_parent:raise ValueError('child exceeds filled parent')
        self.event_ids.add(event_id);self.closed_children+=qty;return True
    def cancel_unfilled_parent(self):
        self.canceled_parent=self.requested_parent-self.filled_parent
    def override(self,at,decision,reason):
        if decision not in ('carry_overnight','close_when_available'):raise ValueError('unknown override')
        self.manual_overrides.append({'at':at,'decision':decision,'reason':reason,'open_qty':self.open_qty})
    @property
    def open_qty(self):return self.filled_parent-self.closed_children
    def end_session(self):return {'open_qty':self.open_qty,'pending_parent':self.requested_parent-self.filled_parent-self.canceled_parent,'overrides':list(self.manual_overrides)}
