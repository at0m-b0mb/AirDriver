#!/usr/bin/env python3
"""Write ``airdriver/data/chipsets.json`` in the house style.

Why this exists: the database is hand-edited by contributors, and `json.dump`
reformats all 1 200+ ids every time — so a one-line change arrives as a
thousand-line diff that nobody can review. This is the formatter the committed
file was written with, kept in the repo so the next edit is a small diff.

    python3 scripts/fmt_chipsets.py --check   # CI: is it formatted?
    python3 scripts/fmt_chipsets.py           # rewrite it in place

The rules:
  * literal UTF-8 (``ensure_ascii=False``) — chipset notes contain em dashes;
  * two-space indent;
  * a list of scalars goes on one line when the whole line fits in
    ``INLINE_WIDTH``, otherwise it is packed onto continuation lines **at item
    boundaries** and those lines wrap at the narrower ``PACK_WIDTH`` (never wrap
    a JSON body with textwrap: it breaks inside quoted strings containing spaces
    and emits invalid JSON);
  * a dict inside a list (a driver option, ``kernel_native``) stays on one line
    however long it is, because that is the unit a reviewer reads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: One-line lists may run this wide before they are broken up…
INLINE_WIDTH = 110
#: …and once broken up, the continuation lines wrap here.
PACK_WIDTH = 96

#: Key order inside a chipset entry, so every entry reads the same way.
KEY_ORDER = ["id", "name", "vendor", "wifi", "band", "monitor_mode", "injection",
             "injection_quality", "prefer_out_of_tree", "notes", "adapters",
             "usb_ids", "kernel_native", "drivers", "blacklist"]

DB = Path(__file__).resolve().parent.parent / "airdriver" / "data" / "chipsets.json"


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def _inline(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(", ", ": "))


def _pack(items, indent: int) -> list[str]:
    """Scalars onto as few lines as fit, breaking only between items."""
    pad = " " * indent
    lines: list[str] = []
    cur = ""
    for i, item in enumerate(items):
        tok = _inline(item) + ("," if i < len(items) - 1 else "")
        cand = f"{cur} {tok}" if cur else tok
        if cur and len(pad) + len(cand) > PACK_WIDTH:
            lines.append(pad + cur)
            cur = tok
        else:
            cur = cand
    if cur:
        lines.append(pad + cur)
    return lines


def _render_list(key: str, items: list, indent: int) -> list[str]:
    pad = " " * indent
    one = f"{pad}{_j(key)}: {_inline(items)}"
    if len(one) <= INLINE_WIDTH:
        return [one]
    return [f"{pad}{_j(key)}: ["] + _pack(items, indent + 2) + [pad + "]"]


def _render_chipset(c: dict, indent: int = 4) -> list[str]:
    pad = " " * indent
    out = [pad + "{"]
    keys = [k for k in KEY_ORDER if k in c] + [k for k in c if k not in KEY_ORDER]
    for n, key in enumerate(keys):
        value = c[key]
        tail = "" if n == len(keys) - 1 else ","
        if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
            out.append(f"{pad}  {_j(key)}: [")
            for i, item in enumerate(value):
                out.append(f"{pad}    {_inline(item)}" + ("," if i < len(value) - 1 else ""))
            out.append(f"{pad}  ]" + tail)
        elif isinstance(value, list):
            block = _render_list(key, value, indent + 2)
            block[-1] += tail
            out += block
        else:
            out.append(f"{pad}  {_j(key)}: {_inline(value)}{tail}")
    out.append(pad + "}")
    return out


def dumps(doc: dict) -> str:
    out = ["{"]
    for key, value in doc.items():
        if key == "chipsets":
            continue
        if isinstance(value, list) and all(not isinstance(x, (dict, list)) for x in value):
            block = _render_list(key, value, 2)
            block[-1] += ","
            out += block
        else:
            out.append(f"  {_j(key)}: {_inline(value)},")
    out.append('  "chipsets": [')
    chipsets = doc["chipsets"]
    for i, c in enumerate(chipsets):
        block = _render_chipset(c)
        if i < len(chipsets) - 1:
            block[-1] += ","
        out += block
    out += ["  ]", "}"]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the file is not already formatted")
    ap.add_argument("path", nargs="?", default=str(DB))
    args = ap.parse_args(argv)

    path = Path(args.path)
    current = path.read_text()
    wanted = dumps(json.loads(current))
    if current == wanted:
        print(f"{path.name} is formatted.")
        return 0
    if args.check:
        print(f"{path.name} is NOT formatted — run: python3 scripts/fmt_chipsets.py",
              file=sys.stderr)
        return 1
    path.write_text(wanted)
    print(f"Reformatted {path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
