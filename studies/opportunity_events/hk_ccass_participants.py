"""Retrieve or parse a bounded set of HKEX CCASS participant snapshots."""

import http.cookiejar
import json
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


URL = "https://www3.hkexnews.hk/sdw/search/searchsdw.aspx"


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}
        self.rows = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == "input" and data.get("name"):
            self.fields[data["name"]] = data.get("value", "")
        if tag == "tr":
            self.current = []

    def handle_data(self, text):
        if self.current is not None and text.strip():
            self.current.append(text.strip())

    def handle_endtag(self, tag):
        if tag == "tr" and self.current is not None:
            self.rows.append(self.current)
            self.current = None


def parse(body, code, day):
    page = Page()
    page.feed(body)
    if page.fields.get("originalShareholdingDate") != day.replace("-", "/"):
        raise ValueError("HKEX returned a different date")
    if page.fields.get("txtStockCode", "").lstrip("0") != code.lstrip("0"):
        raise ValueError("HKEX returned a different stock")
    participants = {}
    for row in page.rows:
        if len(row) >= 10 and row[0] == "Participant ID:":
            key = row[1]
            if key in participants:
                raise ValueError("duplicate participant")
            participants[key] = {"name": row[3], "shares": int(row[7].replace(",", "")),
                                 "ratio_pct": float(row[9].rstrip("%"))}
    if not participants:
        raise ValueError("no participant rows")
    return {"code": code, "date": day, "participants": participants}


def retrieve(code, day):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    headers = {"User-Agent": "Mozilla/5.0", "Referer": URL}
    with opener.open(urllib.request.Request(URL, headers=headers), timeout=15) as response:
        page = Page()
        page.feed(response.read().decode("utf-8", "replace"))
    form = page.fields
    form.update({"__EVENTTARGET": "btnSearch", "txtStockCode": code,
                 "txtShareholdingDate": day.replace("-", "/"),
                 "txtStockName": "", "txtParticipantID": "", "txtParticipantName": ""})
    request = urllib.request.Request(URL, data=urllib.parse.urlencode(form).encode(),
                                     headers=headers, method="POST")
    with opener.open(request, timeout=15) as response:
        return response.read().decode("utf-8", "replace")


if __name__ == "__main__":
    code = sys.argv[1]
    directory = Path("data/hk-southbound-20261101/multidimensional")
    directory.mkdir(parents=True, exist_ok=True)
    for day in sys.argv[2:]:
        path = directory / f"ccass-{code}-{day}.html"
        body = path.read_text() if path.exists() else retrieve(code, day)
        data = parse(body, code, day)
        if not path.exists():
            path.write_text(body)
        output = directory / f"ccass-{code}-{day}.json"
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(code, day, "participants", len(data["participants"]), flush=True)
        time.sleep(0.2)
