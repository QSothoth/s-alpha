"""Retrieve dated market-cap checks and historical Southbound data, one-shot."""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from urllib.request import Request, urlopen


def fetch(mode, source, output):
    events = json.loads(Path(source).read_text())["events"]
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    stopped = Event()
    jobs = []
    for event in events:
        day = event["peak"]["peak_date"]
        if mode == "cap":
            jobs.append((event, day, day))
        else:
            year = int(day[:4])
            while year <= 2024:
                start = max(day, f"{year}-01-01")
                end = min("2024-10-31", f"{year + 1}-12-31")
                if start <= end:
                    jobs.append((event, start, end))
                year += 2
    print(mode, "jobs", len(jobs), flush=True)

    def task(job):
        event, start, end = job
        code = event["code"][3:]
        suffix = start if mode == "cap" else f"{start}-{end}"
        destination = target / f"{mode}-{code}-{suffix}.json"
        if destination.exists() or stopped.is_set():
            return
        when = start.replace("-", "年", 1).replace("-", "月", 1) + "日"
        if mode == "cap":
            question = f"{when}{event['name']}({code}.HK)总市值"
        else:
            until = end.replace("-", "年", 1).replace("-", "月", 1) + "日"
            question = f"{event['name']}({code}.HK){when}至{until}每日南向持股数量和南向持股占比"
        for attempt in range(3):
            try:
                req = Request("https://mkapi2.dfcfs.com/finskillshub/api/claw/query",
                    data=json.dumps({"toolQuery": question}, ensure_ascii=False).encode(),
                    headers={"Content-Type": "application/json", "apikey": os.environ["MX_APIKEY"]})
                with urlopen(req, timeout=14) as response:
                    body = json.load(response)
                envelope = body.get("data") or {}
                message = str(body.get("message") or envelope.get("message") or "")
                if "频率过高" in message or "rate limit" in message.lower():
                    stopped.set()
                    print("rate limit reached; stopping", flush=True)
                    return
                if str(body.get("code")) == "113" or str(envelope.get("code")) == "113":
                    stopped.set()
                    print("quota reached; stopping", flush=True)
                    return
                info = (envelope.get("data") or {}).get("searchDataResultDTO") or {}
                tables = info.get("dataTableDTOList") or []
                if not tables:
                    raise ValueError("empty table: " + str(body.get("message", ""))[:80])
                temp = destination.with_suffix(".tmp")
                temp.write_text(json.dumps(body, ensure_ascii=False))
                temp.replace(destination)
                print(mode, code, suffix, "saved", flush=True)
                time.sleep(1)
                return
            except Exception as error:
                if attempt == 2:
                    print(mode, code, suffix, "FAILED", type(error).__name__, str(error)[:100], flush=True)
                    return
                time.sleep(attempt + 1)

    with ThreadPoolExecutor(max_workers=1) as pool:
        list(pool.map(task, jobs))


if __name__ == "__main__":
    fetch(sys.argv[1], sys.argv[2], sys.argv[3])
