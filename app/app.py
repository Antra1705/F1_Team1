"""Interactive simulator for the Predictive TCP project.

Pick TCP variants, a congestion level and the network settings, press Run, and
the app runs the NS-3 simulation live (the compiled tcp-predictor program) and
plots the results. A second mode puts 4 flows of one variant on the link with
4 CUBIC flows to see who gets the bandwidth. Two more tabs show the project's
final results and how Predictive TCP works.

Start it with:  ./app/run_app.sh   (theme in app/.streamlit/config.toml)
Needs NS-3 built with ./build.sh first.
"""

import hashlib
import html
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
GRAPHS = RESULTS / "graphs"
RUNS = Path(__file__).resolve().parent / "runs"
NS3_DIR = Path(os.environ.get("NS3_DIR", Path.home() / "ns-3"))

VARIANTS = ["tahoe", "reno", "cubic", "vegas", "bbr", "predictive"]
NAMES = {"tahoe": "Tahoe", "reno": "Reno", "cubic": "CUBIC", "vegas": "Vegas", "bbr": "BBR",
         "predictive": "Predictive"}
PROPOSED = NAMES["predictive"]
# Series are told apart by colour AND line style (never colour alone)
# Powder-blue broadsheet palette. Text is tonal: ink, muted and faint are darker shades of the
# background's own hue (~195°), so they belong to the page. The accent is an indigo-violet
# reserved for the proposed method. All text >= 4.5:1. Series differ by colour AND line style.
COLORS = {"Tahoe": "#4B626C", "Reno": "#225081", "CUBIC": "#7A5200", "Vegas": "#8A365E", "BBR": "#1F6338",
          "Predictive": "#4B3BA8", "All flows": "#0D2B36"}
DASHES = {"Tahoe": [2, 2], "Reno": [7, 3], "CUBIC": [10, 3, 2, 3], "Vegas": [3, 3], "BBR": [1, 3],
          "Predictive": [1, 0], "All flows": [1, 0]}
LEVELS = {"low": ("Low", "3 on/off flows at 2 Mbps, ~30% load"),
          "medium": ("Medium", "6 on/off flows at 3 Mbps, ~90% load, bursty"),
          "high": ("High", "8 long flows + 2 Mbps UDP, saturated"),
          "single": ("Single", "1 long flow alone on the link")}
SENDERS = {"low": 3, "medium": 6, "high": 9, "single": 1}
SEGMENT = 1448

# ---------------------------------------------------------------------------
# Styling: Swiss/editorial — hairline rules instead of cards, tabular numerals
# ---------------------------------------------------------------------------
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;0,700;1,500;1,600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
:root {
  --paper: #C4E0E8; --panel: #D5EAF0; --ink: #0D2B36; --muted: #254D5B; --faint: #375C67;
  --rule: #93B8C6; --vermilion: #4B3BA8; --vermilion-text: #3F3294; --good: #0F5C4D; --bad: #2F2580;
  --sans: 'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif;
  --mono: 'IBM Plex Mono', ui-monospace, Menlo, monospace;
}
html, body, .stApp { font-family: var(--sans); }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stDecoration"] { display: none; }
.block-container { padding-top: 1.8rem; padding-bottom: 3rem; max-width: 1240px; }
/* Masthead: newspaper nameplate with a double rule */
.masthead { display: grid; grid-template-columns: minmax(0, 1fr) 460px; gap: 2.2rem; align-items: end;
            padding-bottom: 1rem; margin-bottom: 0.25rem; border-bottom: 3px double var(--ink); }
.dateline { display: flex; flex-wrap: wrap; gap: 0 1.1rem; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.12em;
            text-transform: uppercase; color: var(--muted); border-bottom: 1px solid var(--ink);
            padding-bottom: 0.45rem; margin-bottom: 0.7rem; }
.dateline span + span::before { content: "·"; margin-right: 1.1rem; color: var(--faint); }
.masthead h1 { font-family: var(--sans) !important; font-size: 2.7rem; font-weight: 600; letter-spacing: -0.025em;
               line-height: 1.02; margin: 0; padding: 0; color: var(--ink) !important; }
.masthead h1 span { font-family: var(--sans) !important; color: var(--ink) !important; }
.masthead h1 span.hl { font-style: italic; color: var(--vermilion-text) !important; }
.masthead [data-testid="stHeaderActionElements"] { display: none; }
.lede { font-family: var(--sans); font-size: 1.02rem; line-height: 1.55; color: var(--muted); margin: 0.65rem 0 0;
        max-width: 54ch; }
.topology { width: 100%; height: auto; }
.eyebrow { font-size: 0.68rem; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: var(--ink);
           border-bottom: 1px solid var(--ink); padding-bottom: 0.3rem; margin-bottom: 0.6rem; }
@media (max-width: 1000px) { .masthead { grid-template-columns: 1fr; } }
.runline { display: flex; flex-wrap: wrap; gap: 0.3rem 1.4rem; font-size: 0.8rem; color: var(--muted);
           padding: 0.35rem 0 1rem; }
.runline b { color: var(--ink); font-weight: 600; }
.section { display: flex; align-items: baseline; gap: 0.6rem; font-size: 0.7rem; font-weight: 600;
           letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink); border-top: 1px solid var(--ink);
           padding-top: 0.45rem; margin: 1.8rem 0 0.8rem; }
/* Standfirst figures: big serif numerals divided by hairlines */
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border-bottom: 1px solid var(--rule);
        margin-bottom: 0.4rem; }
.kpi { padding: 0.2rem 1.2rem 0.9rem; border-left: 1px solid var(--rule); }
.kpi:first-child { border-left: none; padding-left: 0; }
.kpi .label { font-size: 0.7rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); }
.kpi .value { font-family: var(--sans); font-size: 2.45rem; font-weight: 600; color: var(--ink); line-height: 1.1;
              font-variant-numeric: lining-nums tabular-nums; margin-top: 0.15rem; letter-spacing: -0.01em; }
.kpi.good .value { color: var(--ink); }
.kpi .value small { font-family: var(--mono); font-size: 0.8rem; color: var(--muted); font-weight: 400; margin-left: 0.3rem;
                    letter-spacing: 0; }
.kpi .delta { font-family: var(--mono); font-size: 0.76rem; margin-top: 0.2rem; color: var(--muted); }
.kpi .delta.good { color: var(--good); } .kpi .delta.bad { color: var(--bad); }
@media (max-width: 900px) { .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .kpi:nth-child(3) { border-left: none; padding-left: 0; } }
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
table.data { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
table.data th { font-size: 0.68rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
                color: var(--muted); text-align: right; padding: 0.5rem 0.7rem; border-bottom: 1px solid var(--ink);
                white-space: nowrap; }
table.data td { text-align: right; padding: 0.5rem 0.7rem; border-bottom: 1px solid var(--rule);
                font-family: var(--mono); font-variant-numeric: tabular-nums; color: var(--ink); white-space: nowrap; }
table.data tr:last-child td { border-bottom: 1px solid var(--ink); }
table.data td:first-child, table.data th:first-child { text-align: left; padding-left: 0; }
table.data td:first-child { font-family: inherit; }
table.data tr.proposed td { font-weight: 600; background: rgba(255, 255, 255, 0.38); }
table.data tr.proposed td:first-child { color: var(--vermilion-text); padding-left: 0.5rem;
                                        box-shadow: inset 2px 0 0 var(--vermilion); }
table.data td.best { color: var(--good); font-weight: 600; }
table.data tr.proposed td.text:nth-child(2) { color: var(--vermilion-text); }
table.data td.na { color: var(--faint); }
table.data th.text, table.data td.text { text-align: left; font-family: inherit; white-space: normal; }
table.data tr.group-start td { border-top: 1px solid var(--ink); }
.swatch { display: inline-block; width: 20px; height: 0; border-top: 2px solid; vertical-align: middle; margin-right: 0.55rem; }
tr.proposed .swatch { border-top-width: 3px; }
.note { font-size: 0.8rem !important; color: var(--muted); margin: 0.5rem 0 0.2rem; line-height: 1.5; }
.note em { font-style: italic; }
.share { margin: 0.6rem 0 0.2rem; }
.share .bar { position: relative; display: flex; height: 30px; border: 1px solid var(--ink); }
.share .bar div { display: flex; align-items: center; padding: 0 0.7rem; font-size: 0.78rem; font-weight: 600;
                  color: #FFFFFF; white-space: nowrap; overflow: hidden; letter-spacing: 0.02em; }
.share .fair { position: absolute; left: 50%; top: -6px; bottom: -6px; border-left: 2px solid var(--ink); }
.share .scale { display: flex; justify-content: space-between; font-family: var(--mono); font-size: 0.7rem;
                color: var(--muted); margin-top: 0.35rem; }
[data-testid="stImage"] img { border: 1px solid var(--rule); }
button[kind="primary"] { border-radius: 0 !important; letter-spacing: 0.06em; text-transform: uppercase; font-size: 0.8rem; }
</style>
"""


def topology_svg(level, rate, delay, queue, occupancy=None):
    """Dumbbell diagram, drawn like a textbook figure. After a run, the queue cells fill to the
    measured mean queue; cells past 80% of the buffer are printed in the accent colour."""
    n = SENDERS[level]
    shown = min(n, 4)
    ys = [22 + i * (66 / max(shown - 1, 1)) for i in range(shown)] if shown > 1 else [55]
    ink, muted = "#0D2B36", "#254D5B"
    senders = "".join(f'<circle cx="18" cy="{y:.0f}" r="4.5" fill="#C4E0E8" stroke="{ink}" stroke-width="1.2"/>'
                      f'<line x1="22.5" y1="{y:.0f}" x2="104" y2="55" stroke="{muted}" stroke-width="0.8"/>' for y in ys)
    more = f'<text x="18" y="104" font-size="10" fill="{muted}" text-anchor="middle">×{n}</text>' if n > shown else ""
    slots = 20
    filled = round(slots * min(occupancy / queue, 1)) if occupancy is not None else 0
    cells = "".join(f'<rect x="{150 + k * 7}" y="34" width="5" height="12" '
                    f'fill="{("#4B3BA8" if k >= 0.8 * slots else ink) if k < filled else "none"}" '
                    f'stroke="{ink}" stroke-width="0.6"/>' for k in range(slots))
    caption = (f"buffer {queue} pkt — measured mean {occupancy:.0f}" if occupancy is not None
               else f"buffer {queue} pkt (FIFO)")
    return f"""
<svg class="topology" viewBox="0 0 470 112" role="img" font-family="IBM Plex Sans, sans-serif"
     aria-label="Dumbbell topology: {n} senders, bottleneck {rate} Mbps, {delay} ms, queue {queue} packets">
  {senders}{more}
  <rect x="104" y="43" width="26" height="24" fill="#C4E0E8" stroke="{ink}" stroke-width="1.2"/>
  <text x="117" y="59" font-size="11" text-anchor="middle" fill="{ink}">R1</text>
  {cells}
  <text x="150" y="27" font-size="10.5" fill="{muted}">{caption}</text>
  <line x1="130" y1="55" x2="340" y2="55" stroke="{ink}" stroke-width="3"/>
  <text x="235" y="77" font-size="12" font-weight="600" text-anchor="middle" fill="{ink}">{rate} Mbps · {delay} ms</text>
  <text x="235" y="92" font-size="10.5" text-anchor="middle" fill="{muted}">bottleneck link</text>
  <rect x="340" y="43" width="26" height="24" fill="#C4E0E8" stroke="{ink}" stroke-width="1.2"/>
  <text x="353" y="59" font-size="11" text-anchor="middle" fill="{ink}">R2</text>
  <line x1="366" y1="55" x2="425" y2="55" stroke="{muted}" stroke-width="0.8"/>
  <circle cx="433" cy="55" r="7.5" fill="#C4E0E8" stroke="{ink}" stroke-width="1.2"/>
  <text x="433" y="80" font-size="10.5" text-anchor="middle" fill="{muted}">receiver</text>
  <text x="18" y="12" font-size="10.5" text-anchor="middle" fill="{muted}">senders</text>
</svg>"""


# ---------------------------------------------------------------------------
# Running NS-3
# ---------------------------------------------------------------------------
def find_binary():
    found = sorted((NS3_DIR / "build" / "scratch" / "tcp-predictor").glob("ns3.*-tcp-predictor-*"))
    return found[0] if found else None


def run_one(binary, variant, settings, predictive_args, mix=None):
    """Run one simulation (or reuse an identical earlier one) and return its output folder."""
    args = [f"--variant={variant}", f"--level={settings['level']}", f"--seed={settings['seed']}",
            f"--simTime={settings['sim_time']}", f"--rate={settings['rate']}Mbps",
            f"--delay={settings['delay']}ms", f"--queue={settings['queue']}"]
    if mix:
        args.append(f"--mix={mix}")
    if "predictive" in (variant, mix):
        args += predictive_args
    key = hashlib.sha1(" ".join(args).encode()).hexdigest()[:12]
    out = RUNS / key
    tag = (f"{variant}-vs-{mix}" if mix else variant) + f"_{settings['level']}_s{settings['seed']}"
    if not (out / f"runinfo_{tag}.csv").exists():
        out.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run([str(binary), *args, f"--outDir={out}"], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"NS-3 failed for {variant}:\n{proc.stderr[-2000:]}")
    return out, tag


def load_run(out, tag, sim_time):
    samples = pd.read_csv(out / f"samples_{tag}.csv")
    flows = pd.read_csv(out / f"flowmon_{tag}.csv")
    info = pd.read_csv(out / f"runinfo_{tag}.csv").iloc[0]
    tcp = flows[flows.protocol == "tcp"]
    thr = tcp.throughput_mbps.to_numpy()
    queue = samples.drop_duplicates("time")
    # Same formulas as analysis/compare_variants.py
    metrics = {
        "goodput": samples.thr_mbps.sum() * 0.1 / sim_time,
        "rtt": samples.srtt_ms.mean(),
        "drops": int(queue.drops.sum()),
        "retx": int(tcp.retransmissions.sum()),
        "queue": queue.queue_pkts.mean(),
        "jain": (thr.sum() ** 2 / (len(thr) * (thr ** 2).sum())) if (thr ** 2).sum() > 0 else float("nan"),
        "cuts": int(info.get("proactive_reductions", 0)),
        "reno_mode": float(info.get("competitive_mode_pct", 0.0)),
    }
    return samples, metrics


def time_series(samples, label, smooth):
    window = 10 if smooth else 1
    per_time = samples.groupby("time")
    frame = pd.DataFrame({
        "Total goodput (Mbps)": per_time.thr_mbps.sum(),
        "Mean RTT (ms)": samples[samples.thr_mbps > 0].groupby("time").srtt_ms.mean(),
        "Bottleneck queue (packets)": samples.drop_duplicates("time").set_index("time").queue_pkts,
        "Congestion window, flow 0 (segments)": samples[samples.flow == 0].set_index("time").cwnd_bytes / SEGMENT,
    }).rolling(window, min_periods=1).mean()
    frame = frame.reset_index().melt(id_vars="time", var_name="metric", value_name="value")
    frame["series"] = label
    return frame


def line_chart(data, metric, figure=None, extra_colors=None):
    part = data[data.metric == metric]
    colors = {**COLORS, **(extra_colors or {})}
    domain = list(dict.fromkeys(part.series))
    title = f"Fig. {figure} — {metric}" if figure else metric
    lines = alt.Chart(part).mark_line(interpolate="monotone").encode(
        x=alt.X("time:Q", title="time (s)", axis=alt.Axis(tickCount=7, grid=False)),
        y=alt.Y("value:Q", title=None, axis=alt.Axis(tickCount=4)),
        color=alt.Color("series:N", title=None,
                        scale=alt.Scale(domain=domain, range=[colors.get(d, "#254D5B") for d in domain]),
                        legend=alt.Legend(orient="top", direction="horizontal", symbolType="stroke",
                                          symbolStrokeWidth=2.2, labelFontSize=11, labelColor="#0D2B36", offset=4)),
        strokeDash=alt.StrokeDash("series:N", scale=alt.Scale(domain=domain,
                                  range=[DASHES.get(d, [1, 0]) for d in domain]), legend=None),
        strokeWidth=alt.condition(alt.datum.series == PROPOSED, alt.value(2.4), alt.value(1.2)),
        tooltip=[alt.Tooltip("series:N", title="Series"), alt.Tooltip("time:Q", format=".1f", title="t (s)"),
                 alt.Tooltip("value:Q", format=".2f", title="Value")]).interactive(bind_y=False)
    return (lines.properties(title=alt.TitleParams(title, anchor="start", fontSize=13.5, fontWeight=600,
                                                   font="IBM Plex Sans", color="#0D2B36", offset=8))
            .configure(font="IBM Plex Sans", background="transparent")
            .configure_view(stroke=None)
            .configure_axis(labelColor="#254D5B", titleColor="#254D5B", labelFontSize=11, titleFontSize=11,
                            titleFontWeight=400, domainColor="#0D2B36", tickColor="#0D2B36", gridColor="#A9CAD5",
                            labelFont="IBM Plex Mono"))


def pct(new, old):
    return 100 * (new - old) / old if old else float("nan")


def kpi(label, value, unit="", delta="", tone=""):
    unit_html = f"<small>{unit}</small>" if unit else ""
    return (f'<div class="kpi {tone}"><div class="label">{label}</div><div class="value">{value}{unit_html}</div>'
            f'<div class="delta {tone}">{delta}&nbsp;</div></div>')


def tone(change, lower_is_better=True):
    if change != change or abs(change) < 0.5:
        return ""
    return "good" if (change < 0) == lower_is_better else "bad"


def results_table(rows):
    cols = [("goodput", "Goodput", "Mbps", "{:.2f}", None), ("rtt", "Mean RTT", "ms", "{:.1f}", "min"),
            ("drops", "Drops", "", "{:,}", "min"), ("retx", "Retrans.", "", "{:,}", "min"),
            ("queue", "Queue", "pkts", "{:.1f}", "min"), ("jain", "Fairness", "Jain", "{:.3f}", None),
            ("cuts", "Proactive cuts", "", "{:,}", None), ("reno_mode", "Reno mode", "%", "{:.0f}", None)]
    best = {key: min(r[key] for r in rows) for key, *_, rule in cols if rule == "min"}
    head = "".join(f"<th>{name}{' (' + unit + ')' if unit else ''}</th>" for _, name, unit, _, _ in cols)
    body = []
    for r in rows:
        cells = []
        for key, _, _, fmt, rule in cols:
            if key in ("cuts", "reno_mode") and r["name"] != PROPOSED:
                cells.append('<td class="na">–</td>')
                continue
            cls = ' class="best"' if rule == "min" and len(rows) > 1 and r[key] == best[key] else ""
            cells.append(f"<td{cls}>{fmt.format(r[key])}</td>")
        swatch = (f'<span class="swatch" style="border-color:{COLORS[r["name"]]};'
                  f'border-top-style:{"solid" if r["name"] == PROPOSED else "dashed"}"></span>')
        row_cls = ' class="proposed"' if r["name"] == PROPOSED else ""
        label = r["name"] + (" (proposed)" if r["name"] == PROPOSED else "")
        body.append(f"<tr{row_cls}><td>{swatch}{html.escape(label)}</td>{''.join(cells)}</tr>")
    return (f'<div class="table-wrap"><table class="data"><thead><tr><th>Variant</th>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Predictive TCP Simulator", layout="wide", initial_sidebar_state="expanded")
st.markdown(CSS, unsafe_allow_html=True)
binary = find_binary()

with st.sidebar:
    st.markdown('<div class="eyebrow">Experiment</div>', unsafe_allow_html=True)
    mode = st.segmented_control("Mode", ["Compare variants", "Share with CUBIC"], default="Compare variants",
                                help="Share with CUBIC: even-numbered flows use the chosen variant, "
                                     "odd-numbered flows use CUBIC (4 vs 4).") or "Compare variants"
    if mode == "Compare variants":
        chosen = st.multiselect("TCP variants", VARIANTS, default=["reno", "cubic", "predictive"],
                                format_func=NAMES.get)
        level_options = list(LEVELS)
    else:
        chosen = [st.selectbox("Variant sharing the link with CUBIC", ["predictive", "reno", "vegas", "bbr", "cubic"],
                               format_func=NAMES.get)]
        level_options = ["high", "medium", "low"]
    level = st.selectbox("Congestion level", level_options, index=level_options.index("high"),
                         format_func=lambda k: LEVELS[k][0])
    st.caption(LEVELS[level][1])
    c1, c2 = st.columns(2)
    seed = c1.number_input("Seed", 1, 100, 4, help="Seeds 1–3 were used for training and tuning; "
                                                     "4 and above were never seen.")
    sim_time = c2.number_input("Duration (s)", 10, 120, 60, step=10)

    st.markdown('<div class="eyebrow" style="margin-top:1rem">Bottleneck link</div>', unsafe_allow_html=True)
    rate = st.select_slider("Bandwidth (Mbps)", [2, 5, 10, 20, 50], value=10)
    delay = st.slider("One-way delay (ms)", 5, 100, 20, step=5)
    queue = st.slider("Queue size (packets)", 10, 200, 50, step=10)
    bdp = rate * 1e6 * (2 * delay + 4) / 1000 / 8 / SEGMENT
    st.caption(f"BDP ≈ {bdp:.0f} packets, so the queue is {queue / bdp:.1f} × BDP. "
               "The model was trained at 10 Mbps, 20 ms, 50 packets.")

    with st.expander("Predictive TCP parameters"):
        beta = st.slider("β — window multiplier on High", 0.5, 1.0, 0.8, step=0.05,
                         help="Tuned value 0.8 (cut 20%). 1.0 means never cut.")
        min_window = st.slider("Minimum window (segments)", 1, 10, 4,
                               help="Below this the predictor never acts. Tuned value 4.")
        detector = st.toggle("Competition detector", value=True,
                             help="Behave like Reno while a loss-based sender keeps the queue full.")
        comp_window = st.slider("Detector window (s)", 1, 8, 2, disabled=not detector)
        comp_threshold = st.slider("Detector threshold (min RTT ÷ base RTT)", 1.05, 2.0, 1.4, step=0.05,
                                   disabled=not detector)
        comp_hold = st.slider("Detector hold (s)", 0, 20, 5, disabled=not detector)
    smooth = st.toggle("Smooth charts (1 s moving average)", value=True)
    run = st.button("Run simulation", type="primary", width="stretch", disabled=binary is None or not chosen)
    st.caption(f"{len(chosen)} simulation{'s' if len(chosen) != 1 else ''} · about "
               f"{max(1, round(1.3 * sim_time / 60 * max(1, len(chosen) / 4)))} s")

# First visit: run the default experiment so the page opens with real data
if binary is not None and chosen and (run or "last" not in st.session_state):
    settings = {"level": level, "seed": int(seed), "sim_time": int(sim_time), "rate": rate, "delay": delay,
                "queue": queue}
    predictive_args = [f"--ns3::TcpPredictive::Beta={beta}", f"--ns3::TcpPredictive::MinWindow={min_window}",
                       f"--ns3::TcpPredictive::CompetitionWindow={comp_window if detector else 0}s",
                       f"--ns3::TcpPredictive::CompetitionThreshold={comp_threshold}",
                       f"--ns3::TcpPredictive::CompetitionHold={comp_hold}s"]
    mix = "cubic" if mode != "Compare variants" else None
    with st.spinner(f"Running {len(chosen)} NS-3 simulation{'s' if len(chosen) != 1 else ''}…"):
        try:
            start = time.time()
            with ThreadPoolExecutor(max_workers=min(6, os.cpu_count() or 2)) as pool:
                jobs = {v: pool.submit(run_one, binary, v, settings, predictive_args, mix) for v in chosen}
                outputs = {v: job.result() for v, job in jobs.items()}
            st.session_state["last"] = (settings, outputs, mix, time.time() - start, detector)
        except RuntimeError as err:
            st.error(str(err))


# Predictive TCP's measured mean queue, shown in the topology diagram
occupancy = None
if "last" in st.session_state:
    _settings, _outputs, _mix, *_ = st.session_state["last"]
    if "predictive" in _outputs and _settings["queue"] == queue:
        _samples = pd.read_csv(_outputs["predictive"][0] / f"samples_{_outputs['predictive'][1]}.csv")
        occupancy = _samples.drop_duplicates("time").queue_pkts.mean()

st.markdown(f"""
<div class="dateline"><span>BCSE308L Computer Networks</span><span>NS-3.48 discrete-event simulation</span></div>
<div class="masthead">
  <div>
    <h1><span class="hl">Predictive</span> TCP</h1>
    <p class="lede">A sender that sees congestion coming. Every run below is a live NS-3 simulation of the
    network on the right; Predictive TCP uses a learned decision tree to ease off before the queue overflows.</p>
  </div>
  {topology_svg(level, rate, delay, queue, occupancy)}
</div>""", unsafe_allow_html=True)

tab_sim, tab_results, tab_how = st.tabs(["Live simulation", "Project results", "How it works"])

with tab_sim:
    if binary is None:
        st.error(f"NS-3 program not found under {NS3_DIR}/build/scratch/tcp-predictor. "
                 "Build it first with ./build.sh (or set NS3_DIR).")
    if "last" in st.session_state:
        settings, outputs, mix, elapsed, detector_on = st.session_state["last"]
        sim = settings["sim_time"]
        lvl = LEVELS[settings["level"]][0]
        st.markdown(f"""<div class="runline"><span><b>{lvl} load</b> · {LEVELS[settings['level']][1]}</span>
            <span>seed <b>{settings['seed']}</b></span><span><b>{sim} s</b> simulated</span>
            <span><b>{settings['rate']} Mbps</b> · {settings['delay']} ms · {settings['queue']}-packet queue</span>
            <span>{"from cache (same settings as an earlier run)" if elapsed < 0.15 else f"computed in {elapsed:.1f} s"}</span>
            </div>""", unsafe_allow_html=True)

        if mix is None:
            rows, series = [], []
            for v, (out, tag) in outputs.items():
                samples, metrics = load_run(out, tag, sim)
                rows.append({"name": NAMES[v], **metrics})
                series.append(time_series(samples, NAMES[v], smooth))
            by_name = {r["name"]: r for r in rows}
            if PROPOSED in by_name and "Reno" in by_name:
                p, r = by_name[PROPOSED], by_name["Reno"]
                d_drop, d_rtt = pct(p["drops"], r["drops"]), pct(p["rtt"], r["rtt"])
                st.markdown('<div class="kpis">'
                            + kpi("Bottleneck drops", f"{p['drops']:,}", "",
                                  f"{d_drop:+.0f}% vs Reno ({r['drops']:,})" if r["drops"] else f"Reno {r['drops']}",
                                  tone(d_drop))
                            + kpi("Mean RTT", f"{p['rtt']:.1f}", "ms", f"{d_rtt:+.1f}% vs Reno ({r['rtt']:.1f})",
                                  tone(d_rtt))
                            + kpi("Goodput", f"{p['goodput']:.2f}", "Mbps",
                                  f"{100 * p['goodput'] / r['goodput']:.1f}% of Reno")
                            + kpi("Fairness (Jain)", f"{p['jain']:.3f}", "", f"Reno {r['jain']:.3f}")
                            + "</div>", unsafe_allow_html=True)
                st.markdown(f'<div class="note">Figures for Predictive TCP; the line below each compares it with Reno '
                            f'in the same run (same seed, so the same traffic).</div>', unsafe_allow_html=True)

            st.markdown('<div class="section">All variants</div>', unsafe_allow_html=True)
            st.markdown(results_table(rows), unsafe_allow_html=True)
            st.markdown('<div class="note">Green = lowest in the column. Proactive cuts and Reno mode '
                        '(competition detector active) apply to Predictive TCP only.</div>', unsafe_allow_html=True)

            st.markdown('<div class="section">Over time</div>', unsafe_allow_html=True)
            data = pd.concat(series)
            metrics_order = data.metric.unique().tolist()
            for k, (left, right) in enumerate([metrics_order[:2], metrics_order[2:]]):
                c1, c2 = st.columns(2, gap="large")
                c1.altair_chart(line_chart(data, left, 2 * k + 1), width="stretch", height=280)
                c2.altair_chart(line_chart(data, right, 2 * k + 2), width="stretch", height=280)
            st.markdown('<div class="note">Drag to pan, scroll to zoom, hover for values. Lines differ in colour '
                        'and dash pattern; Predictive is the thick solid line.</div>', unsafe_allow_html=True)
            st.download_button("Download time series (CSV)",
                               data.pivot_table(index=["time", "series"], columns="metric", values="value")
                               .reset_index().to_csv(index=False), file_name="simulation_timeseries.csv")
        else:
            (v, (out, tag)), = outputs.items()
            samples, metrics = load_run(out, tag, sim)
            mbit = samples.groupby("flow").thr_mbps.sum() * 0.1
            own, cubic = mbit[mbit.index % 2 == 0].sum(), mbit[mbit.index % 2 == 1].sum()
            share = 100 * own / (own + cubic)
            name = NAMES[v]
            detector_note = (f"{metrics['reno_mode']:.0f}%" if v == "predictive" and detector_on
                             else "off" if v == "predictive" else "–")
            st.markdown('<div class="kpis">'
                        + kpi(f"{name} share", f"{share:.1f}", "%", f"{share - 50:+.1f} pts vs fair 50%",
                              "good" if abs(share - 50) < 5 else "bad")
                        + kpi(f"{name} flows (4)", f"{own / sim:.2f}", "Mbps")
                        + kpi("CUBIC flows (4)", f"{cubic / sim:.2f}", "Mbps")
                        + kpi("Time in Reno mode", detector_note, "",
                              "competition detector" if v == "predictive" else "")
                        + "</div>", unsafe_allow_html=True)
            own_color = COLORS.get(name, "#254D5B")
            st.markdown(f"""<div class="share"><div class="bar">
                <div style="width:{share:.1f}%;background:{own_color}">{html.escape(name)} {share:.0f}%</div>
                <div style="width:{100 - share:.1f}%;background:#254D5B">CUBIC {100 - share:.0f}%</div>
                <span class="fair" title="fair share"></span></div>
                <div class="scale"><span>0%</span><span>fair 50%</span><span>100%</span></div></div>""",
                        unsafe_allow_html=True)
            st.markdown('<div class="note">Reference over 10 seeds: CUBIC 48%, Reno 45%, Vegas 34%, Predictive 40% '
                        'with the detector (23% without), BBR 95%.</div>', unsafe_allow_html=True)

            st.markdown('<div class="section">Over time</div>', unsafe_allow_html=True)
            group = samples.assign(series=samples.flow.mod(2).map({0: name, 1: "CUBIC"}))
            window = 10 if smooth else 1
            per_group = (group.groupby(["time", "series"]).thr_mbps.sum().unstack()
                         .rolling(window, min_periods=1).mean().reset_index()
                         .melt(id_vars="time", var_name="series", value_name="value"))
            per_group["metric"] = "Goodput of each group (Mbps)"
            st.altair_chart(line_chart(per_group, "Goodput of each group (Mbps)", 1), width="stretch", height=280)
            both = time_series(samples, "All flows", smooth)
            c1, c2 = st.columns(2, gap="large")
            c1.altair_chart(line_chart(both, "Mean RTT (ms)", 2), width="stretch", height=260)
            c2.altair_chart(line_chart(both, "Bottleneck queue (packets)", 3), width="stretch", height=260)

with tab_results:
    st.markdown('<div class="section">Final results · mean ± std over 10 seeds × 60 s · 10 Mbps / 20 ms / '
                '50-packet queue</div>', unsafe_allow_html=True)
    final = RESULTS / "final_table.csv"
    if final.exists():
        table = pd.read_csv(final)
        text_cols = {"Level", "Variant"}
        head = "".join(f'<th class="text">{html.escape(c)}</th>' if c in text_cols else f"<th>{html.escape(c)}</th>"
                       for c in table.columns)
        rows_html, previous = [], None
        for r in table.itertuples(index=False):
            classes = (["proposed"] if "Predictive" in r.Variant else []) + (["group-start"] if r.Level != previous else [])
            cells = []
            for col, value in zip(table.columns, r):
                if col == "Level":
                    value = value.capitalize() if r.Level != previous else ""
                cells.append(f'<td class="text">{html.escape(str(value))}</td>' if col in text_cols
                             else f"<td>{html.escape(str(value))}</td>")
            previous = r.Level
            rows_html.append(f'<tr class="{" ".join(classes)}">{"".join(cells)}</tr>')
        body = "".join(rows_html)
        st.markdown(f'<div class="table-wrap"><table class="data"><thead><tr>{head}</tr></thead>'
                    f'<tbody>{body}</tbody></table></div>',
                    unsafe_allow_html=True)
    else:
        st.warning("results/final_table.csv not found. Run ./run_all.sh first.")
    for title, files in [
        ("Comparison of all variants", ["comparison_bars.png", "tradeoff_delay_loss.png",
                                        "predictive_improvement.png"]),
        ("Behaviour over time (seed 4, unseen)", ["timeseries_high.png", "timeseries_medium.png"]),
        ("Robustness", ["robustness_buffer.png", "mixed_competition.png", "competition_tuning.png"]),
        ("Machine learning", ["ml_feature_sets.png", "ml_confusion_matrices.png", "ml_early_warning.png"]),
        ("Tuning and ablation", ["tuning_grid.png", "ablation_tradeoff.png", "validation_cwnd.png"]),
    ]:
        st.markdown(f'<div class="section">{title}</div>', unsafe_allow_html=True)
        with st.expander("Show graphs", expanded=title.startswith("Comparison")):
            for name in files:
                if (GRAPHS / name).exists():
                    st.image(str(GRAPHS / name), width="stretch")
    st.markdown('<div class="note">Full tables and explanations: results/RESULTS.md. Findings and limitations: '
                'README.md.</div>', unsafe_allow_html=True)

with tab_how:
    st.markdown('<div class="section">The model · a 4-leaf decision tree, evaluated every 100 ms</div>',
                unsafe_allow_html=True)
    st.markdown("""<div class="table-wrap"><table class="data"><thead><tr><th class="text">RTT ÷ min RTT</th>
<th class="text">RTT ÷ its 1 s average</th><th class="text">Prediction, 0.5 s ahead</th><th class="text">Action</th>
</tr></thead><tbody>
<tr><td class="text">≤ 1.23</td><td class="text">–</td><td class="text">Low</td>
<td class="text">Normal Reno growth</td></tr>
<tr><td class="text">&gt; 1.23 (queue building)</td><td class="text">≤ 0.85 (queue draining fast)</td>
<td class="text">Medium</td><td class="text">Grow at 25% of Reno's rate</td></tr>
<tr class="proposed"><td class="text">&gt; 1.23 (queue building)</td><td class="text">&gt; 0.85</td>
<td class="text">High</td><td class="text">Cut cwnd by 20%, at most once per RTT; stop growing</td></tr>
</tbody></table></div>""", unsafe_allow_html=True)
    st.markdown("""
<div class="section">Why it works</div>

- **Learned, not hand-tuned:** trained on 106,354 samples of Tahoe, Reno and CUBIC traffic, each labelled with the
  real router queue 0.5 s later. Out of 5 candidate models, this one was chosen **by running each inside NS-3**,
  not by offline accuracy.
- **Sender-side only:** it uses nothing but the sender's own RTT measurements. The router queue is used only to
  label the training data.
- **Competition detector:** if the lowest RTT over 2 s stays above 1.4 × the base RTT, the queue never drained,
  so a loss-based sender such as CUBIC is assumed and Predictive TCP behaves like Reno for at least 5 s. The base
  RTT is the lowest raw RTT sample, so flows that start behind a full queue still learn the true base RTT.
- **Safety net:** Reno's normal loss response still applies, and the predictor never acts below a 4-segment window.
""", unsafe_allow_html=True)
    header = ROOT / "ns3" / "predictive-model.h"
    st.markdown('<div class="section">Generated code</div>', unsafe_allow_html=True)
    if header.exists():
        with st.expander("predictive-model.h (generated by analysis/export_tree.py)"):
            st.code(header.read_text(), language="cpp")
    if (GRAPHS / "ml_decision_tree.png").exists():
        with st.expander("The trained tree (scikit-learn)"):
            st.image(str(GRAPHS / "ml_decision_tree.png"), width="stretch")
