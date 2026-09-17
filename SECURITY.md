# Security

AirDriver installs kernel drivers, so it runs as **root** and executes shell
commands. That makes its threat model worth stating plainly.

## Reporting a vulnerability

Please open a [security advisory](https://github.com/at0m-b0mb/AirDriver/security/advisories/new)
rather than a public issue, and give it a few days before disclosing.

## What AirDriver trusts, and what it doesn't

### The chipset database is executable content

`airdriver/data/chipsets.json` is not merely data. Its `package`, `module`,
`repo`, `path` and `blacklist` values end up inside commands that run as root,
so **a chipset entry is a small program**, and the database is contributed to by
pull request. Two layers keep that safe:

1. **Rejected at the gate.** `airdriver db --check` — which runs in CI on every
   push and pull request — validates each of those fields against a strict
   whitelist of shapes (`ChipsetDB.problems()`). A value carrying shell
   metacharacters fails review instead of reaching a user's machine. `repo` is
   pinned to `https://` specifically because git's `ext::` transport executes an
   arbitrary command, and `path` may not escape `data/`.
2. **Quoted at the point of use.** Every such value is `shlex.quote`d where it is
   interpolated, so even a hand-edited or downgraded database cannot break out of
   a command.

`tests/test_security.py` holds regression tests for both layers.

### Device-supplied data is untrusted

A USB device controls its own descriptors. Vendor and product IDs are parsed
through a strict `[0-9a-f]{4}` filter (`detector._hex4`) before being used, and
device-supplied *strings* are only ever displayed, never executed. Monitor-mode
helpers pass interface names as argument **lists**, never through a shell.

### Command-line arguments

`modeswitch` validates its target is a literal `vid:pid`; `rebuild` quotes its
target. You are already root when you run these, so this is defence in depth
rather than a privilege boundary — but it keeps AirDriver safe to drive from a
script.

### What AirDriver deliberately does *not* defend against

* **The driver sources themselves.** Out-of-tree Wi-Fi drivers are cloned from
  upstream repositories (morrownr, aircrack-ng, lwfinger) and **compiled and
  installed as root** — that is what installing a driver means. AirDriver pins
  the transport to https and the repository list is reviewable in the database,
  but a compromised upstream repository is a compromised driver. This is
  inherent, and it is why the repository list is short and well-known.
* **`curl | sudo bash`.** The one-line installer runs a script from this
  repository as root. If you would rather read it first, clone and run
  `sudo ./install.sh` — the README documents both.
* **Anything requiring a password you choose.** MOK enrollment
  (`mokutil --import`) is never automated; AirDriver prints the instructions and
  hands it to you.

## Responsible use

AirDriver enables monitor mode and packet injection for **authorized** testing,
research and education. Using them against networks you do not own or have
written permission to test may be illegal.
