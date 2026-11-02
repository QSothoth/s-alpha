"""Stream selected CCASS observations from Webb-site's public 7z MySQL dump.

The compressed archive is read locally through libarchive.  The SQL is never
extracted to disk or loaded as a whole.  The dump stores only changes, so each
participant's latest row on or before a snapshot is carried forward.
"""

import argparse
import ctypes
import json
import re
from pathlib import Path


ISSUES = {
    30520: ("HK.01024", "2021-11-01", "2022-01-25"),
    33377: ("HK.01880", "2023-10-27", "2024-01-24"),
    24979: ("HK.02269", "2025-02-18", "2025-05-20"),
    3606: ("HK.02318", "2024-11-05", "2025-02-05"),
    26823: ("HK.03690", "2023-02-10", "2023-05-11"),
    11742: ("HK.09988", "2025-02-14", "2025-05-16"),
}
SOUTH_IDS = {1323, 1456}
ID_PATTERN = b"(?:" + b"|".join(str(i).encode() for i in ISSUES) + b")"
MARKER = re.compile(rb"Dumping data for table `([^`]+)`")
DAILY = re.compile(rb"\('(\d{4}-\d\d-\d\d)',(" + ID_PATTERN + rb"),([0-9,]+)\)")
HOLDING = re.compile(rb"\((\d+),(" + ID_PATTERN + rb"),(\d+),'(\d{4}-\d\d-\d\d)'\)")


class Selector:
    def __init__(self):
        self.table = b""
        self.tail = b""
        self.daily = {}
        self.snapshots = {}
        self.south = {}
        self.participants = bytearray()
        self.tables_seen = set()

    def scan(self, data, limit):
        if self.table == b"dailylog":
            for match in DAILY.finditer(data):
                if match.start() >= limit:
                    break
                day = match[1].decode()
                issue = int(match[2])
                if day not in ISSUES[issue][1:]:
                    continue
                values = [int(v) for v in match[3].split(b",")]
                if len(values) != 10:
                    raise ValueError(f"Unexpected dailylog fields: {len(values)}")
                self.daily[f"{issue}:{day}"] = values
        elif self.table == b"holdings":
            for match in HOLDING.finditer(data):
                if match.start() >= limit:
                    break
                participant, issue, amount = map(int, match.group(1, 2, 3))
                day = match[4].decode()
                for snapshot in ISSUES[issue][1:]:
                    if day <= snapshot:
                        key = f"{issue}:{snapshot}"
                        by_participant = self.snapshots.setdefault(key, {})
                        previous = by_participant.get(str(participant))
                        if previous is None or previous[0] < day:
                            by_participant[str(participant)] = [day, amount]
                if participant in SOUTH_IDS:
                    self.south.setdefault(f"{issue}:{participant}", []).append([day, amount])
        elif self.table == b"participants" and limit:
            self.participants.extend(data[:limit])
            if len(self.participants) > 16 * 1024 * 1024:
                raise ValueError("Unexpectedly large participants table")

    def feed(self, block, final=False):
        data = self.tail + block
        cutoff = len(data) if final else max(0, len(data) - 512)
        cursor = 0
        for marker in MARKER.finditer(data):
            if marker.start() >= cutoff:
                break
            self.scan(data[cursor:marker.start()], marker.start() - cursor)
            self.table = marker[1]
            self.tables_seen.add(self.table.decode())
            cursor = marker.end()
        self.scan(data[cursor:], max(0, cutoff - cursor))
        self.tail = data[cutoff:]


def read_archive(path):
    library = ctypes.CDLL("libarchive.so.13")
    ptr = ctypes.c_void_p
    library.archive_read_new.restype = ptr
    for name in ("archive_read_support_filter_all", "archive_read_support_format_all", "archive_read_free"):
        function = getattr(library, name)
        function.argtypes = [ptr]
        function.restype = ctypes.c_int
    library.archive_read_open_filename.argtypes = [ptr, ctypes.c_char_p, ctypes.c_size_t]
    library.archive_read_open_filename.restype = ctypes.c_int
    library.archive_read_next_header.argtypes = [ptr, ctypes.POINTER(ptr)]
    library.archive_read_next_header.restype = ctypes.c_int
    library.archive_read_data.argtypes = [ptr, ptr, ctypes.c_size_t]
    library.archive_read_data.restype = ctypes.c_ssize_t
    library.archive_error_string.argtypes = [ptr]
    library.archive_error_string.restype = ctypes.c_char_p
    archive = library.archive_read_new()
    try:
        library.archive_read_support_filter_all(archive)
        library.archive_read_support_format_all(archive)
        if library.archive_read_open_filename(archive, str(path).encode(), 65536) != 0:
            raise RuntimeError(library.archive_error_string(archive))
        entry = ptr()
        if library.archive_read_next_header(archive, ctypes.byref(entry)) != 0:
            raise RuntimeError(library.archive_error_string(archive))
        buf = ctypes.create_string_buffer(1024 * 1024)
        while True:
            n = library.archive_read_data(archive, buf, len(buf))
            if n < 0:
                raise RuntimeError(library.archive_error_string(archive))
            if n == 0:
                return
            yield buf.raw[:n]
    finally:
        library.archive_read_free(archive)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    selector = Selector()
    read_bytes = 0
    for block in read_archive(args.archive):
        selector.feed(block)
        read_bytes += len(block)
        if read_bytes % (1024**3) == 0:
            print(f"Decoded {read_bytes // 1024**3} GiB; table {selector.table.decode()}", flush=True)
    selector.feed(b"", final=True)
    expected = len(ISSUES) * 2
    if len(selector.daily) != expected or len(selector.snapshots) != expected:
        raise ValueError(f"Incomplete snapshots: daily={len(selector.daily)} holdings={len(selector.snapshots)}")
    if not {"dailylog", "holdings", "participants"}.issubset(selector.tables_seen):
        raise ValueError("Required dump tables were not seen")
    result = {
        "issues": ISSUES,
        "dailylog": selector.daily,
        "snapshots": selector.snapshots,
        "south_history": selector.south,
        "tables_seen": sorted(selector.tables_seen),
    }
    args.output.write_text(json.dumps(result, separators=(",", ":")))
    args.output.with_suffix(".participants.sql").write_bytes(selector.participants)
    print(f"Wrote {args.output}; decoded {read_bytes} bytes", flush=True)


if __name__ == "__main__":
    main()
