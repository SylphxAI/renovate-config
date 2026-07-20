#!/usr/bin/env python3
import json
import pathlib
import sys

ok = False
for name in ("default.json", "renovate.json"):
    path = pathlib.Path(name)
    if path.exists():
        json.loads(path.read_text())
        print("ok", path)
        ok = True
if not ok:
    print("missing default.json/renovate.json", file=sys.stderr)
    sys.exit(1)
