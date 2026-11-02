"""One-shot, paged download of available Eastmoney Southbound holdings."""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def fetch(candidates_path, output_dir):
    candidates = json.loads(Path(candidates_path).read_text())["stocks"]
    codes = sorted({s["code"].split(".")[1] for s in candidates
                    if int(s["code"].split(".")[1]) < 80000})
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    params = {"reportName": "RPT_MUTUAL_STOCK_HOLDRANKS",
              "columns": "SECURITY_CODE,HOLD_DATE,MUTUAL_TYPE,HOLD_SHARES,HOLD_SHARES_RATIO,IS_ADJ_DATE,EX_DIVIDEND_DATE",
              "pageSize": 500, "sortColumns": "SECURITY_CODE,HOLD_DATE", "sortTypes": "1,1",
              "filter": '(SECURITY_CODE in (' + ','.join('"' + c + '"' for c in codes)
                        + '))(MUTUAL_TYPE="002")(HOLD_DATE<=\'2026-10-30\')'}

    def page(number):
        dest = target / f"{number:04}.json"
        if dest.exists():
            return json.loads(dest.read_text())
        for attempt in range(3):
            try:
                url = "https://datacenter-web.eastmoney.com/api/data/v1/get?" + urlencode(
                    dict(params, pageNumber=number))
                req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(req, timeout=15) as response:
                    body = json.load(response)
                if not body.get("success") or not body.get("result"):
                    raise ValueError(str(body.get("message", "empty response")))
                data = body["result"]
                temp = dest.with_suffix(".tmp")
                temp.write_text(json.dumps(data, ensure_ascii=False))
                temp.replace(dest)
                print("page", number, "rows", len(data.get("data") or []), flush=True)
                return data
            except Exception as error:
                if attempt == 2:
                    print("page", number, "FAILED", type(error).__name__, str(error)[:100], flush=True)
                    return None
                time.sleep(1 + attempt)

    first = page(1)
    if first is None:
        raise RuntimeError("Cannot fetch first page")
    total = first["pages"]
    print("candidate_codes", len(codes), "rows", first["count"], "pages", total, flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        pages = list(pool.map(page, range(2, total + 1)))
    missing = [i for i, item in enumerate(pages, 2) if item is None]
    print("missing_pages", missing, flush=True)
    return missing


if __name__ == "__main__":
    if fetch(sys.argv[1], sys.argv[2]):
        raise SystemExit(1)
