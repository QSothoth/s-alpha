"""Summarise selected Webb-site snapshots and check their reconstruction."""

import json
import sys
from pathlib import Path

from studies.opportunity_events.hk_webb_ccass import ISSUES


GROUPS = {
    "south": (1323, 1456),
    "three_custodians": (454, 460, 30),
    "futu": (1243,),
}


def summary(data):
    result = []
    for issue, (code, first, last) in ISSUES.items():
        observations = []
        for date in (first, last):
            key = f"{issue}:{date}"
            snapshots = data["snapshots"][key]
            daily = data["dailylog"][key]
            holdings = [entry[1] for entry in snapshots.values()]
            named = daily[0] + daily[4]
            investor = daily[2] + daily[4]
            groups = {}
            for name, participants in GROUPS.items():
                groups[name] = (sum(snapshots[str(p)][1] for p in participants)
                                if all(str(p) in snapshots for p in participants) else None)
            observations.append({
                "date": date,
                "top5_named_pct": 100 * daily[6] / named if named else None,
                "top10_named_pct": 100 * daily[7] / named if named else None,
                "direct_investor_ccass_pct": 100 * investor / (named + daily[2]) if named + daily[2] else None,
                "direct_investor_count": daily[3] + daily[5],
                "named_holdings_match": sum(holdings) == named,
                "top5_holdings_match": sum(sorted(holdings, reverse=True)[:5]) == daily[6],
                "groups": groups,
            })
        result.append({"code": code, "issue": issue, "observations": observations})
    return result


if __name__ == "__main__":
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    destination.write_text(json.dumps(summary(json.loads(source.read_text())), indent=2))
