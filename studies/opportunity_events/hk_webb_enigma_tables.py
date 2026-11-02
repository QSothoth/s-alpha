"""Copy a few Enigma tables from a 7z SQL dump to bounded gzip streams."""

import gzip
import shutil
import sys
from pathlib import Path

from studies.opportunity_events.hk_webb_ccass import MARKER, read_archive


class TableCopies:
    def __init__(self, directory):
        self.files = {name: gzip.open(directory / (name + ".sql.gz"), "wb", compresslevel=1)
                      for name in ("issue", "issuedshares", "sectypes", "stocklistings")}
        self.table = ""
        self.tail = b""
        self.seen = set()

    def write(self, data):
        if self.table in self.files:
            self.files[self.table].write(data)

    def feed(self, block, final=False):
        data = self.tail + block
        cutoff = len(data) if final else max(0, len(data) - 512)
        cursor = 0
        for marker in MARKER.finditer(data):
            if marker.start() >= cutoff:
                break
            self.write(data[cursor:marker.start()])
            self.table = marker[1].decode()
            self.seen.add(self.table)
            if self.table in self.files:
                print(f"Copying {self.table}", flush=True)
            cursor = marker.end()
        self.write(data[cursor:cutoff])
        self.tail = data[cutoff:]

    def close(self):
        for file in self.files.values():
            file.close()


def main():
    archive, directory = Path(sys.argv[1]), Path(sys.argv[2])
    copies = TableCopies(directory)
    read_bytes = 0
    try:
        for block in read_archive(archive):
            copies.feed(block)
            read_bytes += len(block)
            if read_bytes % (1024**3) == 0:
                if shutil.disk_usage(directory).free < 2 * 1024**3:
                    raise RuntimeError("Stopped: less than 2 GiB disk free")
                print(f"Decoded {read_bytes // 1024**3} GiB; table {copies.table}", flush=True)
        copies.feed(b"", final=True)
        missing = set(copies.files) - copies.seen
        if missing:
            raise ValueError(f"Missing tables: {sorted(missing)}")
    finally:
        copies.close()
    print(f"Copied selected tables after decoding {read_bytes} bytes", flush=True)


if __name__ == "__main__":
    main()
