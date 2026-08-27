#!/usr/bin/env python3
"""Generate the GitHub Pages site into docs/ from the chipset database.

The site's centrepiece is a searchable view of every chipset AirDriver knows,
so it has to be generated rather than hand-written: 52 families and 1258 ids
would rot the moment the database changed. Run `make site` after editing
airdriver/data/chipsets.json.
"""
from __future__ import annotations

import html
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from airdriver.core.chipset_db import ChipsetDB          # noqa: E402
from airdriver.version import __version__, __codename__  # noqa: E402

REPO = "https://github.com/at0m-b0mb/AirDriver"


def rank(c) -> int:
    """Sort best-for-pentest first: injection quality, then monitor support."""
    q = {"excellent": 4, "good": 3, "fair": 2, "poor": 1, "unknown": 0}
    return (q.get(c.injection_quality, 0) * 4
            + (2 if c.injection else 0) + (1 if c.monitor_mode else 0))


def build_rows(db: ChipsetDB) -> list[dict]:
    rows = []
    for c in sorted(db.all(), key=rank, reverse=True):
        methods = []
        for d in c.best_drivers():
            methods.append({"kernel_native": "in-kernel", "apt": "apt",
                            "dkms_git": "DKMS", "offline": "offline"}.get(d.method, d.method))
        seen, path = set(), []
        for m in methods:
            if m not in seen:
                seen.add(m); path.append(m)
        rows.append({
            "id": c.id, "name": c.name, "vendor": c.vendor, "wifi": c.wifi,
            "band": c.band, "monitor": c.monitor_mode, "injection": c.injection,
            "quality": c.injection_quality, "notes": c.notes,
            "adapters": list(c.adapters), "ids": list(c.usb_ids),
            "native": c.kernel_native.module if c.kernel_native else "",
            "path": " → ".join(path),
        })
    return rows


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AirDriver — Wi-Fi adapter driver auto-installer for Kali &amp; Parrot</title>
<meta name="description" content="AirDriver identifies your Wi-Fi adapter and installs a driver that actually works on Kali Linux and Parrot OS. __FAMILIES__ chipset families, __IDS__ USB/PCI IDs, with honest monitor-mode and injection flags.">
<meta property="og:title" content="AirDriver — Wi-Fi driver auto-installer for Kali &amp; Parrot">
<meta property="og:description" content="__FAMILIES__ chipset families · __IDS__ USB/PCI IDs · honest monitor/injection flags.">
<meta property="og:image" content="__REPO__/raw/main/docs/banner.png">
<meta property="og:type" content="website">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='14' font-size='14'>📡</text></svg>">
<style>
  :root{
    --bg:#0b0f14; --surface:#131a23; --surface2:#182130; --line:#243044;
    --text:#e6edf3; --dim:#8b98a5; --faint:#5d6b7a;
    --green:#2ee6a6; --green-d:#1f9e72; --blue:#38bdf8; --amber:#f5a623; --red:#f2726f;
    --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }
  *{box-sizing:border-box}
  html{scroll-behavior:smooth;scroll-padding-top:70px}
  body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);
       line-height:1.65;-webkit-font-smoothing:antialiased}
  a{color:var(--blue);text-decoration:none}
  a:hover{text-decoration:underline}
  code,kbd{font-family:var(--mono);font-size:.9em}
  .wrap{max-width:1120px;margin:0 auto;padding:0 20px}

  nav{position:sticky;top:0;z-index:50;background:rgba(11,15,20,.86);
      backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
  nav .wrap{display:flex;align-items:center;gap:22px;height:58px}
  nav .brand{font-weight:700;letter-spacing:-.2px;color:var(--text)}
  nav .brand span{color:var(--green)}
  nav .links{display:flex;gap:18px;margin-left:auto;flex-wrap:wrap}
  nav .links a{color:var(--dim);font-size:.92rem}
  nav .links a:hover{color:var(--text);text-decoration:none}

  header.hero{padding:56px 0 40px;border-bottom:1px solid var(--line);
    background:radial-gradient(900px 380px at 12% -10%,rgba(31,158,114,.18),transparent 60%)}
  .hero img.banner{width:100%;height:auto;border-radius:14px;border:1px solid var(--line);display:block}
  .tagline{font-size:1.12rem;color:var(--dim);margin:22px 0 6px;max-width:70ch}
  .badges{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 4px}
  .badge{font-size:.78rem;padding:4px 11px;border-radius:999px;
    border:1px solid var(--line);background:var(--surface);color:var(--dim)}
  .badge.g{color:var(--green);border-color:rgba(46,230,166,.35)}
  .cta{display:flex;gap:12px;flex-wrap:wrap;margin-top:24px}
  .btn{display:inline-block;padding:10px 20px;border-radius:9px;font-weight:600;font-size:.95rem}
  .btn.primary{background:var(--green-d);color:#fff;border:1px solid var(--green-d)}
  .btn.primary:hover{background:var(--green);color:#04241a;text-decoration:none}
  .btn.ghost{border:1px solid var(--line);color:var(--text);background:var(--surface)}
  .btn.ghost:hover{border-color:var(--green-d);text-decoration:none}

  section{padding:56px 0;border-bottom:1px solid var(--line)}
  h2{font-size:1.6rem;margin:0 0 6px;letter-spacing:-.4px}
  h3{font-size:1.06rem;margin:26px 0 8px}
  .sub{color:var(--dim);margin:0 0 26px;max-width:74ch}

  pre{background:var(--surface);border:1px solid var(--line);border-radius:10px;
      padding:14px 16px;overflow-x:auto;margin:12px 0}
  pre code{color:var(--text)}
  .c-comment{color:var(--faint)}
  .c-cmd{color:var(--green)}

  .grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px 20px}
  .card h4{margin:0 0 6px;font-size:1rem}
  .card p{margin:0;color:var(--dim);font-size:.93rem}

  .callout{border-left:3px solid var(--amber);background:rgba(245,166,35,.07);
    border-radius:0 10px 10px 0;padding:14px 18px;margin:20px 0}
  .callout.good{border-left-color:var(--green-d);background:rgba(31,158,114,.08)}
  .callout p{margin:0;color:var(--dim);font-size:.94rem}
  .callout strong{color:var(--text)}

  /* chipset browser */
  .controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:16px}
  .controls input[type=search]{flex:1 1 300px;background:var(--surface);color:var(--text);
    border:1px solid var(--line);border-radius:9px;padding:11px 14px;font-size:.95rem;font-family:var(--mono)}
  .controls input[type=search]:focus{outline:none;border-color:var(--green-d)}
  .filter{font-size:.83rem;padding:7px 13px;border-radius:999px;cursor:pointer;
    border:1px solid var(--line);background:var(--surface);color:var(--dim);user-select:none}
  .filter[aria-pressed=true]{background:var(--green-d);border-color:var(--green-d);color:#fff}
  .count{color:var(--faint);font-size:.86rem;margin-left:auto;font-family:var(--mono)}

  .tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--surface)}
  table{border-collapse:collapse;width:100%;font-size:.9rem;min-width:820px}
  th,td{text-align:left;padding:11px 14px;border-bottom:1px solid var(--line);vertical-align:top}
  th{background:var(--surface2);color:var(--dim);font-weight:600;font-size:.78rem;
     text-transform:uppercase;letter-spacing:.06em;position:sticky;top:58px;z-index:1}
  tbody tr:last-child td{border-bottom:none}
  tbody tr.chip-row{cursor:pointer}
  tbody tr.chip-row:hover{background:var(--surface2)}
  .yes{color:var(--green)} .no{color:var(--red)} .maybe{color:var(--amber)}
  .q{font-size:.76rem;padding:2px 8px;border-radius:999px;border:1px solid var(--line);color:var(--dim)}
  .q.excellent{color:var(--green);border-color:rgba(46,230,166,.4)}
  .q.good{color:var(--green);border-color:rgba(46,230,166,.25)}
  .q.fair{color:var(--amber);border-color:rgba(245,166,35,.3)}
  .q.poor,.q.unknown{color:var(--faint)}
  .name{font-weight:600;color:var(--text)}
  .vendor{color:var(--faint);font-size:.8rem;display:block}
  .detail td{background:var(--bg);color:var(--dim);font-size:.88rem}
  .detail .ids{font-family:var(--mono);font-size:.78rem;color:var(--faint);
    word-break:break-all;margin-top:8px;line-height:1.9}
  .detail .ids b{color:var(--dim);font-weight:400}
  .hidden{display:none}
  .empty{padding:30px;text-align:center;color:var(--faint)}

  .mermaid{background:var(--surface);border:1px solid var(--line);
    border-radius:12px;padding:18px;overflow-x:auto;text-align:center}
  footer{padding:36px 0 60px;color:var(--faint);font-size:.88rem}
  footer a{color:var(--dim)}
  @media (max-width:640px){
    header.hero{padding:34px 0 28px} section{padding:40px 0}
    th{position:static} nav .links a:nth-child(n+4){display:none}
  }
</style>
</head>
<body>

<nav><div class="wrap">
  <span class="brand">Air<span>Driver</span></span>
  <span class="links">
    <a href="#install">Install</a>
    <a href="#how">How it works</a>
    <a href="#chipsets">Chipsets</a>
    <a href="#honesty">Capability flags</a>
    <a href="#cli">CLI</a>
    <a href="#trouble">Troubleshooting</a>
    <a href="__REPO__">GitHub&nbsp;↗</a>
  </span>
</div></nav>

<header class="hero"><div class="wrap">
  <img class="banner" src="banner.png" alt="AirDriver — Wi-Fi adapter driver auto-installer for Kali Linux and Parrot OS">
  <p class="tagline">Plug in your adapter. AirDriver identifies the chipset, picks a driver path that
  can actually succeed on your kernel, installs it, brings the interface up — then tells you
  honestly whether it worked.</p>
  <div class="badges">
    <span class="badge g">v__VERSION__ · __CODENAME__</span>
    <span class="badge">__FAMILIES__ chipset families</span>
    <span class="badge">__IDS__ USB/PCI IDs</span>
    <span class="badge">Kali · Parrot · Debian · Ubuntu</span>
    <span class="badge">Python 3.9+ · stdlib core</span>
    <span class="badge">MIT</span>
  </div>
  <div class="cta">
    <a class="btn primary" href="#install">Install it</a>
    <a class="btn ghost" href="#chipsets">Is my adapter supported?</a>
    <a class="btn ghost" href="__REPO__">Source on GitHub</a>
  </div>
</div></header>

<section id="install"><div class="wrap">
  <h2>Install</h2>
  <p class="sub">One line on Kali, Parrot, Debian or Ubuntu. The installer pulls the build
  prerequisites, the Qt runtime libraries the GUI needs, creates an isolated virtualenv and
  drops an <code>airdriver</code> launcher on your PATH.</p>
<pre><code><span class="c-comment"># one-liner</span>
<span class="c-cmd">curl -fsSL __REPO__/raw/main/install.sh | sudo bash</span>

<span class="c-comment"># or from a clone</span>
<span class="c-cmd">git clone __REPO__.git &amp;&amp; cd AirDriver</span>
<span class="c-cmd">sudo ./install.sh</span>

<span class="c-comment"># then</span>
<span class="c-cmd">airdriver</span>              <span class="c-comment"># GUI</span>
<span class="c-cmd">airdriver scan</span>         <span class="c-comment"># CLI: what's plugged in?</span>
<span class="c-cmd">sudo airdriver install</span> <span class="c-comment"># plan + install a driver</span></code></pre>
  <div class="callout good"><p><strong>No internet on the target box?</strong> That's the catch-22
  AirDriver exists for — no Wi-Fi driver means no connection to download the driver. Run
  <code>./scripts/fetch_offline_drivers.sh</code> while you still have a connection to bundle the
  driver sources, then install air-gapped.</p></div>
</div></section>

<section id="how"><div class="wrap">
  <h2>How driver selection works</h2>
  <p class="sub">AirDriver prefers the in-kernel driver whenever your kernel is new enough, because
  the fastest DKMS build is the one that never runs. Everything after the install matters just as
  much: a loaded module is not a working adapter until the radio is unblocked and the interface is up.</p>
  <pre class="mermaid">__MERMAID__</pre>
  <div class="grid" style="margin-top:22px">
    <div class="card"><h4>Skips pointless builds</h4><p>If your kernel already ships a working
      driver for the chip, AirDriver loads and verifies it instead of compiling anything.</p></div>
    <div class="card"><h4>Falls back automatically</h4><p>When the distro's DKMS package is missing
      or lagging your kernel, the same step compiles the maintainer's driver from source instead
      of just failing.</p></div>
    <div class="card"><h4>Finishes the job</h4><p><code>rfkill unblock</code>, <code>ip link set
      up</code>, <code>nmcli radio wifi on</code> — the steps people forget, which is why a
      "successful" install so often looks dead.</p></div>
    <div class="card"><h4>Tells the truth after</h4><p>Verification checks built / loaded / bound
      and reports <em>why</em> not: Secure Boot, rfkill, missing firmware, no interface.</p></div>
  </div>
</div></section>

<section id="chipsets"><div class="wrap">
  <h2>Chipset database</h2>
  <p class="sub">Every chipset AirDriver recognises, with honest monitor-mode and injection flags —
  search by chipset, vendor, adapter model, or a raw <code>vid:pid</code>. Click a row for the full
  ID list and notes. Useful before you buy, not just after.</p>
  <div class="controls">
    <input type="search" id="q" placeholder="RTL8812AU · Alfa AWUS036ACH · 0bda:8812 · mediatek" autocomplete="off" spellcheck="false">
    <button class="filter" id="f-mon" aria-pressed="false">Monitor mode</button>
    <button class="filter" id="f-inj" aria-pressed="false">Injection</button>
    <span class="count" id="count"></span>
  </div>
  <div class="tablewrap">
    <table>
      <thead><tr>
        <th>Chipset</th><th>Bands</th><th>Monitor</th><th>Injection</th>
        <th>Quality</th><th>Driver path</th><th>IDs</th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
    <div class="empty hidden" id="empty">No chipset matches that. If it's your adapter, run
      <code>airdriver contribute</code> — it builds a pre-filled report so the database learns it.</div>
  </div>
</div></section>

<section id="honesty"><div class="wrap">
  <h2>Where the capability flags come from</h2>
  <p class="sub">Monitor mode and injection are the whole reason to pick one adapter over another, so
  those flags are read out of the kernel's own source rather than asserted from reputation.</p>
  <div class="grid">
    <div class="card"><h4>mac80211 always adds monitor</h4><p><code>net/mac80211/main.c</code> sets
      <code>interface_modes |= BIT(NL80211_IFTYPE_MONITOR)</code> under the comment
      <em>"mac80211 always supports monitor"</em>. Every softmac driver inherits it — which is why
      legacy USB parts are flagged monitor-capable even where their own driver advertises only
      station mode.</p></div>
    <div class="card"><h4>ath11k takes it back, per chip</h4><p><code>supports_monitor</code> is
      <strong>false</strong> for QCA6390 and WCN6855, and ath11k clears the monitor iftype right
      after registration. Those are in a huge share of 2021+ laptops.</p></div>
    <div class="card"><h4>ath12k restores it</h4><p>WCN7850 sets <code>supports_monitor = true</code>,
      so the Wi-Fi 7 part <em>can</em> sniff where its QCA6390 predecessor cannot. They are separate
      entries so one flag cannot launder the other.</p></div>
    <div class="card"><h4>brcmfmac is FullMAC</h4><p>It never goes through mac80211 and only offers
      monitor when firmware reports the feature — which consumer firmware doesn't. That's Raspberry
      Pi and MacBook Wi-Fi, flagged accordingly.</p></div>
  </div>
  <div class="callout"><p><strong>If your laptop has a QCA6390 or WCN6855, monitor mode is not
  available at all.</strong> Not flaky — never offered. No <code>airmon-ng</code> invocation changes
  it, because the driver removes the capability before you ever get there. Use an external adapter
  from the attack-grade list above.</p></div>
  <div class="callout"><p><strong>Injection is only claimed where there's a track record.</strong>
  ath11k, ath12k and AR5523 are flagged <em>unknown</em> rather than <em>yes</em>, and
  <code>airdriver recommend</code> won't put them forward for attack work. Promising injection the
  tool can't stand behind is worse than admitting the gap.</p></div>
</div></section>

<section id="cli"><div class="wrap">
  <h2>Command line</h2>
  <p class="sub">The core and CLI are pure standard library, so everything works over SSH on a
  headless box with nothing installed.</p>
<pre><code><span class="c-cmd">airdriver scan</span>              <span class="c-comment"># detected adapters + chipset match</span>
<span class="c-cmd">airdriver doctor</span>            <span class="c-comment"># headers, DKMS, Secure Boot, build tools</span>
<span class="c-cmd">airdriver info 0bda:8812</span>    <span class="c-comment"># everything known about a chipset</span>
<span class="c-cmd">airdriver install --dry-run</span> <span class="c-comment"># preview the exact plan, change nothing</span>
<span class="c-cmd">airdriver verify</span>            <span class="c-comment"># is it really installed, loaded and bound?</span>
<span class="c-cmd">airdriver diagnose</span>          <span class="c-comment"># one shareable block for a help thread</span>

<span class="c-comment"># the lifecycle around an install</span>
<span class="c-cmd">airdriver status</span>            <span class="c-comment"># what's installed, built for this kernel?</span>
<span class="c-cmd">sudo airdriver rebuild</span>      <span class="c-comment"># after a kernel upgrade broke Wi-Fi</span>
<span class="c-cmd">sudo airdriver sign</span>         <span class="c-comment"># sign modules so Secure Boot loads them</span>
<span class="c-cmd">sudo airdriver modeswitch</span>   <span class="c-comment"># kick a "driver CD-ROM" dongle into Wi-Fi mode</span>
<span class="c-cmd">airdriver recommend</span>         <span class="c-comment"># which adapter should I actually buy?</span>
<span class="c-cmd">airdriver contribute</span>        <span class="c-comment"># report an unknown adapter</span></code></pre>
</div></section>

<section id="trouble"><div class="wrap">
  <h2>Troubleshooting</h2>
  <div class="grid">
    <div class="card"><h4>Wi-Fi broke after an update</h4><p>A new kernel means your out-of-tree
      module was never built for it. <code>sudo airdriver rebuild</code>. This is the single most
      common Kali Wi-Fi failure.</p></div>
    <div class="card"><h4>"Installed" but the adapter is dead</h4><p>Usually rfkill or Secure Boot.
      <code>airdriver verify</code> names which, with the fix. Then
      <code>sudo airdriver diagnose</code> if you need to ask someone.</p></div>
    <div class="card"><h4>Secure Boot refuses the module</h4><p>A fresh DKMS module is unsigned.
      <code>sudo airdriver sign</code> generates a key and signs it; enrolling is one manual
      <code>mokutil</code> step plus a reboot, printed for you.</p></div>
    <div class="card"><h4>Dongle shows up as a CD-ROM</h4><p>Many cheap adapters enumerate as fake
      storage holding Windows drivers. <code>sudo airdriver modeswitch</code> ejects it so it
      re-appears as Wi-Fi — under a <em>different</em> USB id.</p></div>
    <div class="card"><h4>Adapter not recognised</h4><p><code>airdriver contribute</code> assembles
      the descriptors, kernel and dmesg into a pre-filled issue. It never sends anything on its own,
      and never collects your serial number.</p></div>
    <div class="card"><h4>Nothing detected at all</h4><p>Detection reads sysfs directly, so an empty
      list really means the kernel sees no wireless hardware. Try another port — high-power cards
      want USB 3.0 or a powered hub.</p></div>
  </div>
</div></section>

<footer><div class="wrap">
  AirDriver v__VERSION__ “__CODENAME__” · MIT · built by
  <a href="https://github.com/at0m-b0mb">at0m-b0mb</a> ·
  <a href="__REPO__">source</a> ·
  <a href="__REPO__/blob/main/CHANGELOG.md">changelog</a> ·
  <a href="__REPO__/issues/new?labels=new-adapter">report an adapter</a>
  <br><br>
  Database: __FAMILIES__ chipset families, __IDS__ USB/PCI IDs — every one taken from a kernel
  driver's own device table. This page is generated from
  <a href="__REPO__/blob/main/airdriver/data/chipsets.json">chipsets.json</a>, so it cannot drift
  from what the tool actually knows.
</div></footer>

<script>
const DATA = __DATA__;
const rowsEl = document.getElementById('rows');
const emptyEl = document.getElementById('empty');
const countEl = document.getElementById('count');
const qEl = document.getElementById('q');
const fMon = document.getElementById('f-mon');
const fInj = document.getElementById('f-inj');

const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const mark = b => b ? '<span class="yes">yes</span>' : '<span class="no">no</span>';

function render(list){
  rowsEl.innerHTML = list.map((c, i) => {
    const inj = c.injection ? '<span class="yes">yes</span>'
              : (c.quality === 'unknown' ? '<span class="maybe">unknown</span>' : '<span class="no">no</span>');
    return `<tr class="chip-row" data-i="${i}">
      <td><span class="name">${esc(c.name)}</span><span class="vendor">${esc(c.vendor)} · ${esc(c.wifi)}</span></td>
      <td>${esc(c.band)}</td>
      <td>${mark(c.monitor)}</td>
      <td>${inj}</td>
      <td><span class="q ${esc(c.quality)}">${esc(c.quality)}</span></td>
      <td>${esc(c.path)}${c.native ? `<span class="vendor">${esc(c.native)}</span>` : ''}</td>
      <td>${c.ids.length}</td>
    </tr>
    <tr class="detail hidden" data-d="${i}"><td colspan="7">
      ${esc(c.notes)}
      ${c.adapters.length ? `<div style="margin-top:8px"><b style="color:var(--dim);font-weight:600">Known adapters:</b> ${esc(c.adapters.join(', '))}</div>` : ''}
      <div class="ids"><b>${c.ids.length} IDs:</b> ${c.ids.map(esc).join('  ')}</div>
    </td></tr>`;
  }).join('');
  countEl.textContent = `${list.length} of ${DATA.length} families · ${list.reduce((n,c)=>n+c.ids.length,0)} IDs`;
  emptyEl.classList.toggle('hidden', list.length > 0);
}

function apply(){
  const q = qEl.value.trim().toLowerCase();
  const needMon = fMon.getAttribute('aria-pressed') === 'true';
  const needInj = fInj.getAttribute('aria-pressed') === 'true';
  render(DATA.filter(c => {
    if (needMon && !c.monitor) return false;
    if (needInj && !c.injection) return false;
    if (!q) return true;
    return (c.name + ' ' + c.vendor + ' ' + c.wifi + ' ' + c.band + ' ' + c.id + ' ' +
            c.adapters.join(' ') + ' ' + c.ids.join(' ') + ' ' + c.notes).toLowerCase().includes(q);
  }));
}

rowsEl.addEventListener('click', e => {
  const tr = e.target.closest('tr.chip-row');
  if (!tr) return;
  const d = rowsEl.querySelector(`tr.detail[data-d="${tr.dataset.i}"]`);
  if (d) d.classList.toggle('hidden');
});
[fMon, fInj].forEach(b => b.addEventListener('click', () => {
  b.setAttribute('aria-pressed', b.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
  apply();
}));
qEl.addEventListener('input', apply);
apply();

// Deep-link straight to a vid:pid, e.g. #q=0bda:8812
if (location.hash.startsWith('#q=')) {
  qEl.value = decodeURIComponent(location.hash.slice(3));
  apply();
  document.getElementById('chipsets').scrollIntoView();
}
</script>
<script type="module">
  // Progressive enhancement: if the CDN is unreachable the <pre> simply stays as text.
  try {
    const {default: mermaid} = await import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs');
    mermaid.initialize({startOnLoad:false, theme:'dark',
      themeVariables:{background:'#131a23', primaryColor:'#182130', lineColor:'#5d6b7a'}});
    await mermaid.run({querySelector:'.mermaid'});
  } catch (e) { /* leave the source visible */ }
</script>
</body>
</html>
"""


def main() -> int:
    db = ChipsetDB.load()
    rows = build_rows(db)
    mermaid = (ROOT / "README.md").read_text(encoding="utf-8")
    start = mermaid.index("```mermaid") + len("```mermaid\n")
    mermaid = mermaid[start:mermaid.index("```", start)].rstrip()

    page = (TEMPLATE
            .replace("__DATA__", json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
            .replace("__MERMAID__", html.escape(mermaid))
            .replace("__FAMILIES__", str(len(db)))
            .replace("__IDS__", str(db.usb_id_count()))
            .replace("__VERSION__", __version__)
            .replace("__CODENAME__", __codename__)
            .replace("__REPO__", REPO))

    out = ROOT / "docs" / "index.html"
    out.write_text(page, encoding="utf-8")
    # Pages runs Jekyll by default, which would ignore files it doesn't like.
    (ROOT / "docs" / ".nojekyll").write_text("")
    print(f"wrote {out.relative_to(ROOT)}  ({len(page)//1024} KB, "
          f"{len(db)} families, {db.usb_id_count()} ids)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
