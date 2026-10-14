# tools/generate_step41_profile_step40_joint_baseline.py
# -*- coding: utf-8 -*-

"""Step41：把 Step40 knee 默认值固化成可切换 profile，并做回归 baseline。

输出：
  - reports/step41_profile_step40_joint_baseline.json
  - reports/step41_profile_step40_joint_baseline.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    rep40 = repo / 'reports' / 'step40_joint_pareto_baseline.json'
    if not rep40.exists():
        raise SystemExit(f"missing: {rep40}")
    data40 = json.loads(rep40.read_text(encoding='utf-8'))
    knee = data40.get('knee', {})
    knee_scan = knee.get('scan', {})
    knee_sweep = knee.get('sweep', {})

    from rtl.gc_profile_params import get_profile
    prof = get_profile('step40_joint')
    prof_scan = prof['scan']
    prof_sweep = prof['sweep']

    def _norm_scan(d: Dict[str, Any]) -> Dict[str, int]:
        return dict(
            cardset_size=int(d['cardset_size']),
            fifo_depth=int(d['fifo_depth']),
            consume_every=int(d['consume_every']),
            batch_size=int(d['batch_size']),
        )

    def _norm_sweep(d: Dict[str, Any]) -> Dict[str, int]:
        return dict(sets=int(d['sets']), ways=int(d['ways']), index_mode=int(d['index_mode']))

    out = {
        'step40_knee': {'scan': _norm_scan(knee_scan), 'sweep': _norm_sweep(knee_sweep)},
        'profile_step40_joint': {'scan': _norm_scan(prof_scan), 'sweep': _norm_sweep(prof_sweep), 'note': prof.get('note', '')},
    }
    out['matches'] = (out['step40_knee'] == {'scan': out['profile_step40_joint']['scan'], 'sweep': out['profile_step40_joint']['sweep']})

    out_json = repo / 'reports' / 'step41_profile_step40_joint_baseline.json'
    out_md = repo / 'reports' / 'step41_profile_step40_joint_baseline.md'
    out_json.write_text(json.dumps(out, indent=2, sort_keys=True), encoding='utf-8')

    md = []
    md.append('# Step41 baseline: profile(step40_joint)\n')
    md.append('## Step40 knee\n')
    md.append(f"- scan: {out['step40_knee']['scan']}\n")
    md.append(f"- sweep: {out['step40_knee']['sweep']}\n")
    md.append('\n## profile: step40_joint\n')
    md.append(f"- scan: {out['profile_step40_joint']['scan']}\n")
    md.append(f"- sweep: {out['profile_step40_joint']['sweep']}\n")
    if out['profile_step40_joint']['note']:
        md.append(f"- note: {out['profile_step40_joint']['note']}\n")
    md.append(f"\n## matches: {out['matches']}\n")
    out_md.write_text(''.join(md), encoding='utf-8')

    print('OK: wrote step41 profile baseline to reports/.')


if __name__ == '__main__':
    main()
