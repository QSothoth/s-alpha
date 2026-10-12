"""Ask one agent harness to TAKE or SKIP every card, several times each (study agent_card_eval).

    python3 -m studies.agent_card_eval.code.run --cards <dir with cards.jsonl> \
        --harness codex --reps 3 --out <raw dir> [--jobs 3]

Each call is saved as <out>/<card_id>.<rep>.json (decision, raw text, usage, seconds).
Existing files are kept, so an interrupted run resumes where it stopped.
"""
import argparse
import json
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DECISIONS = ('TAKE', 'SKIP')
EFFORT = None  # codex model_reasoning_effort override (A2 B4); None keeps the user's config


def _codex(prompt, workdir):
    last = Path(workdir) / 'last.txt'
    effort = ['-c', 'model_reasoning_effort="%s"' % EFFORT] if EFFORT else []
    proc = subprocess.run(['codex', 'exec', '--skip-git-repo-check', '--ephemeral', '-s', 'read-only', '--json', *effort,
                           '-o', str(last), prompt], cwd=workdir, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=600)
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip().startswith('{')]
    usage = next((e['usage'] for e in reversed(events) if e.get('type') == 'turn.completed'), None)
    return proc.returncode, last.read_text(encoding='utf-8') if last.exists() else '', usage, None


def _claude(prompt, workdir):
    proc = subprocess.run(['claude', '-p', prompt, '--output-format', 'json', '--tools', '', '--max-budget-usd', '1'],
                          cwd=workdir, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
    out = json.loads(proc.stdout or '{}')
    return proc.returncode, out.get('result', ''), out.get('usage'), out.get('total_cost_usd')


def _grok(prompt, workdir):
    proc = subprocess.run(['grok', '-p', prompt, '--output-format', 'json', '--max-turns', '1', '--tools', ''],
                          cwd=workdir, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900)
    out = json.loads(proc.stdout or '{}')
    return proc.returncode, out.get('text', ''), out.get('usage'), out.get('total_cost_usd')


HARNESSES = {'codex': _codex, 'claude': _claude, 'grok': _grok}


def parse_answer(text):
    text = text.strip()
    if text.startswith('```'):
        text = text.strip('`').removeprefix('json').strip()
    try:
        answer = json.loads(text)
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None


def parse_decision(text):
    """The answer must be one JSON object with decision TAKE or SKIP; anything else is invalid."""
    decision = (parse_answer(text) or {}).get('decision')
    return decision if decision in DECISIONS else None


def parse_probability(text):
    """A2 B2: one JSON object with p_big_win in [0, 1]; anything else is invalid."""
    p = (parse_answer(text) or {}).get('p_big_win')
    return float(p) if isinstance(p, (int, float)) and not isinstance(p, bool) and 0 <= p <= 1 else None


def ask(harness, card, rep, out, prompt_path):
    path = out / ('%s.%d.json' % (card['card_id'], rep))
    if path.exists():
        return path
    prompt = Path(prompt_path).read_text(encoding='utf-8') + json.dumps(card, separators=(',', ':'))
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as workdir:  # empty cwd: no repository files in reach
        try:
            code, text, usage, cost = HARNESSES[harness](prompt, workdir)
        except (subprocess.TimeoutExpired, ValueError) as exc:
            code, text, usage, cost = None, '', None, None
            text = 'ERROR: %s' % exc
    record = {'card_id': card['card_id'], 'rep': rep, 'harness': harness, 'exit_code': code,
              'decision': parse_decision(text), 'p_big_win': parse_probability(text), 'text': text, 'usage': usage, 'cost_usd': cost,
              'seconds': round(time.monotonic() - started, 1)}
    path.write_text(json.dumps(record, ensure_ascii=False) + '\n', encoding='utf-8')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--cards', required=True)
    parser.add_argument('--harness', required=True, choices=sorted(HARNESSES))
    parser.add_argument('--reps', type=int, default=3)
    parser.add_argument('--out', required=True)
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--prompt', default=str(Path(__file__).with_name('prompt.txt')))
    parser.add_argument('--effort', default=None, help='codex reasoning effort override')
    args = parser.parse_args(argv)
    global EFFORT
    EFFORT = args.effort
    cards = [json.loads(line) for line in (Path(args.cards) / 'cards.jsonl').read_text(encoding='utf-8').splitlines()]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(card, rep) for rep in range(args.reps) for card in cards]
    with ThreadPoolExecutor(args.jobs) as pool:
        for i, path in enumerate(pool.map(lambda job: ask(args.harness, *job, out, args.prompt), jobs), 1):
            if i % 20 == 0 or i == len(jobs):
                print('%d/%d %s' % (i, len(jobs), path.name), flush=True)


if __name__ == '__main__':
    main()
