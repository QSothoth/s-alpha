"""Five configuration sections, with read-only aliases for historical flat keys."""
from collections.abc import Mapping
from types import MappingProxyType

import numpy as np

from .regime import NAMES

SECTIONS = ('universe', 'signal', 'allocate', 'trade', 'switch')
ALLOCATION_RULES = frozenset(('max_open', 'max_open_by_kind', 'max_new_long', 'max_new_by_kind',
    'max_new_all', 'max_new_year', 'no_rebuy_day', 'rotate_min_days', 'rotate_below',
    'make_room_kind', 'make_room_confirmed', 'rotate_score', 'rotate_actual_adds'))
LAYERS = {**dict.fromkeys(('pool', 'ep_pool'), 'universe'),
          **dict.fromkeys(('max_new', 'cooldown', 'daily_cap', *ALLOCATION_RULES), 'allocate'),
          **dict.fromkeys(('stop', 'stop_min', 'stop_cap_max', 'small_cap', 'gap_size', 'exits',
                           'gross', 'risk', 'risk_high', 'max_position', 'rule_opts', 'short',
                           'shorts', 'short_size', 'short_days', 'short_last'), 'trade'),
          **dict.fromkeys(('filter', 'short_gate'), 'switch')}


def _freeze(x):
    if isinstance(x, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in x.items()})
    return tuple(_freeze(v) for v in x) if isinstance(x, (list, tuple)) else x


def plain(x):
    if isinstance(x, Mapping):
        return {k: plain(v) for k, v in x.items()}
    return [plain(v) for v in x] if isinstance(x, (list, tuple)) else x


class Config(Mapping):
    """Iteration serializes sections; cfg['risk'] can read the alias, never write it.

    Unknown legacy keys belong to signal unless the study supplies a key->layer
    map. New round files use sections explicitly; they never guess ownership.
    """
    def __init__(self, cfg, layers=None, *, regime_frozen=False, state=None):
        owners = dict(LAYERS, **(layers or {}))
        self._by_state, self._common = {}, {}
        parts = {}
        for key in SECTIONS:
            section = cfg.get(key, {})
            # Historical flat `common` is also a shared-mechanism parameter.
            # The explicit by_state key distinguishes the workflow envelope.
            if 'by_state' in section:
                if set(section)-{'common', 'by_state'}:
                    raise ValueError('common/by_state cannot mix with flat section keys')
                changes = section.get('by_state', {})
                if changes and not regime_frozen:
                    raise ValueError('by_state requires a frozen regime')
                if set(changes)-set(NAMES):
                    raise ValueError('unknown market state')
                for change in changes.values():
                    if not isinstance(change, Mapping) or _leaves(change) > 2:
                        raise ValueError('at most two corrections per line and state')
                self._by_state[key] = plain(changes)
                self._common[key] = plain(section.get('common', {}))
                section = _overlay(self._common[key], changes.get(state, {}))
            parts[key] = dict(section)
        if state is not None and state not in NAMES:
            raise ValueError('unknown market state')
        for name in NAMES:
            if sum(_leaves(self._by_state.get(k, {}).get(name, {})) for k in ('universe', 'signal')) > 2:
                raise ValueError('at most two corrections across the selection line per state')
        self._regime_frozen = regime_frozen
        for key, value in cfg.items():
            if key not in SECTIONS:
                layer = owners.get(key, 'signal')
                if key in parts[layer] and parts[layer][key] != value:
                    raise ValueError('conflicting flat alias: '+key)
                parts[layer][key] = value
        aliases, locations = {}, {}
        for layer, section in parts.items():
            for key, value in section.items():
                aliases[key] = value
                locations.setdefault(key, []).append(layer)
        collisions = {k for k, layers in locations.items() if len(layers) > 1}
        for key in collisions:
            owner = owners.get(key)
            if owner and key in parts[owner]:
                aliases[key] = parts[owner][key]
            else:
                del aliases[key]
        self._sections, self._aliases = _freeze(parts), _freeze(aliases)
        self._collisions = frozenset(collisions)

    def __getitem__(self, key):
        return self._sections[key] if key in self._sections else self._aliases[key]

    def __iter__(self):
        return iter(SECTIONS)

    def __len__(self):
        return len(SECTIONS)

    def flat(self):
        if self._collisions:
            raise ValueError('use sections for duplicate parameter names: '+', '.join(sorted(self._collisions)))
        return plain(self._aliases)

    def for_state(self, state):
        """Resolve one frozen state's corrections; common remains the default view."""
        return Config({k: dict(common=self._common.get(k, plain(self[k])), by_state=self._by_state.get(k, {}))
                       for k in SECTIONS}, regime_frozen=self._regime_frozen, state=state)


def _leaves(value):
    return sum(_leaves(v) if isinstance(v, Mapping) else 1 for v in value.values())


def _overlay(base, change):
    out = plain(base)
    for key, value in change.items():
        out[key] = (_overlay(out[key], value) if isinstance(value, Mapping)
                    and isinstance(out.get(key), Mapping) else plain(value))
    return out


def flat(cfg):
    return (cfg if isinstance(cfg, Config) else Config(cfg)).flat()


def validate_switch(switch, rules_text):
    """At most two sourced controls; none can express stock ranking or stop width."""
    controls = switch.get('controls', [])
    if len(controls) > 2:
        raise ValueError('a trader has at most two switches')
    seen = set()
    for control in controls:
        field, quote = control['field'], control.get('quote', '')
        if field not in ('sides', 'risk_mult', 'setups', 'max_open', 'rotate') or field in seen:
            raise ValueError('unknown or duplicate switch control: '+field)
        if not quote.strip() or quote not in rules_text:
            raise ValueError('switch must quote RULES_CN verbatim')
        values = control.get('values', {})
        if set(values) != set(NAMES):
            raise ValueError('each switch must specify all three states')
        for value in values.values():
            if field in ('sides', 'setups') and not isinstance(value, (tuple, list)):
                raise ValueError('sides / setups must be lists')
            if field == 'sides' and set(value)-{-1, 1}:
                raise ValueError('sides are -1 and/or 1')
            if field == 'risk_mult' and (not np.isfinite(value) or value < 0):
                raise ValueError('risk multiplier must be finite and nonnegative')
            if field == 'max_open' and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise ValueError('max_open must be a nonnegative integer')
            if field == 'rotate' and not isinstance(value, bool):
                raise ValueError('rotate must be boolean')
        seen.add(field)
    return True
