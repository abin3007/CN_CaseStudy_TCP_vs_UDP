"""
plots.py - turn the CSV results into the graphs used in the report.

Usage:  python plots.py      (after experiment.py has written ../results)
Writes PNG files into ../graphs
"""

import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "results")
OUT = os.path.join(HERE, "..", "graphs")

COL = {"tcp": "#2a78d6", "udp": "#eb6834", "fec": "#1baf7a"}
NAME = {"tcp": "TCP (reliable, in-order)", "udp": "UDP (plain)", "fec": "UDP + FEC"}
MODES = ["tcp", "udp", "fec"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
DEADLINE = 150

plt.rcParams.update({
    "font.size": 10, "axes.edgecolor": INK2, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "axes.axisbelow": True, "figure.dpi": 150,
    "legend.frameon": False,
})


def read(name):
    with open(os.path.join(RES, name)) as f:
        return list(csv.DictReader(f))


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, name), bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def grouped_bars(rows, key, ylabel, title, fname, logy=False, hline=None):
    scen = list(dict.fromkeys(r["scenario"] for r in rows))
    fig, ax = plt.subplots(figsize=(9, 4))
    w = 0.26
    for i, m in enumerate(MODES):
        ys = [float(next(r for r in rows if r["scenario"] == s and r["mode"] == m)[key]) for s in scen]
        xs = [j + (i - 1) * w for j in range(len(scen))]
        ax.bar(xs, ys, w * 0.92, color=COL[m], label=NAME[m])
    ax.set_xticks(range(len(scen)))
    ax.set_xticklabels([s.replace(" (", "\n(") for s in scen], fontsize=8.5)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    if logy:
        ax.set_yscale("log")
    if hline:
        ax.axhline(hline[0], color=INK2, ls="--", lw=1)
        ax.text(len(scen) - 0.5, hline[0], hline[1], ha="right", va="bottom", fontsize=8, color=INK2)
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.18))
    save(fig, fname)


def topology():
    fig, ax = plt.subplots(figsize=(9, 2.6))
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3)
    boxes = [
        (0.2, "Sender\n(video-call app)\nMediaSource 50 pkt/s\n1000 B payload", "#cde2fb"),
        (3.7, "Impaired link\n(netemu.py UDP relay)\nloss | delay | jitter\nbursty loss (Gilbert-Elliott)", "#f0efec"),
        (7.2, "Receiver\n(playback)\nmeasures latency,\nloss, jitter, freezes", "#cde2fb"),
    ]
    for x, txt, c in boxes:
        ax.add_patch(FancyBboxPatch((x, 0.5), 2.6, 2.0, boxstyle="round,pad=0.05", fc=c, ec=INK2))
        ax.text(x + 1.3, 1.5, txt, ha="center", va="center", fontsize=8.5, color=INK)
    kw = dict(arrowstyle="-|>", color=INK, lw=1.4)
    ax.annotate("", xy=(3.7, 1.9), xytext=(2.85, 1.9), arrowprops=kw)
    ax.annotate("", xy=(7.2, 1.9), xytext=(6.35, 1.9), arrowprops=kw)
    ax.annotate("", xy=(2.85, 1.0), xytext=(3.7, 1.0), arrowprops=dict(kw, color=INK2, ls="--"))
    ax.annotate("", xy=(6.35, 1.0), xytext=(7.2, 1.0), arrowprops=dict(kw, color=INK2, ls="--"))
    ax.text(3.27, 2.05, "data", ha="center", fontsize=8)
    ax.text(6.77, 2.05, "data", ha="center", fontsize=8)
    ax.text(3.27, 0.65, "ACKs\n(TCP only)", ha="center", fontsize=7.5, color=INK2)
    ax.text(6.77, 0.65, "ACKs\n(TCP only)", ha="center", fontsize=7.5, color=INK2)
    save(fig, "fig1_topology.png")


def sweep_lines(rows, key, ylabel, title, fname, hline=None, logy=False):
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for m in MODES:
        pts = [(float(r["loss_pct"]), float(r[key])) for r in rows if r["mode"] == m]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], "-o", color=COL[m], lw=2, ms=5, label=NAME[m])
    ax.set_xlabel("Packet loss on the link (%)")
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontsize=11)
    if logy:
        ax.set_yscale("log")
    if hline:
        ax.axhline(hline[0], color=INK2, ls="--", lw=1)
        ax.text(0, hline[0], hline[1], va="bottom", fontsize=8, color=INK2)
    ax.legend(fontsize=8)
    save(fig, fname)


def timeline(tag, label):
    fig, axes = plt.subplots(3, 1, figsize=(9, 6), sharex=True, sharey=True)
    for ax, m in zip(axes, MODES):
        rows = read(os.path.join("packets", f"{tag}_{m}.csv"))
        t = [float(r["gen_time_s"]) for r in rows if r["delivered"] == "1"]
        y = [float(r["latency_ms"]) for r in rows if r["delivered"] == "1"]
        lost = [float(r["gen_time_s"]) for r in rows if r["delivered"] == "0"]
        ax.scatter(t, y, s=4, color=COL[m], lw=0)
        if lost:
            ax.scatter(lost, [2] * len(lost), marker="x", s=14, color=INK, lw=0.8, label="lost packet")
            ax.legend(loc="upper right", fontsize=7.5)
        ax.axhline(DEADLINE, color=INK2, ls="--", lw=1)
        ax.set_yscale("log")
        ax.set_ylim(1, 3000)
        ax.set_ylabel("latency (ms)")
        ax.set_title(NAME[m], loc="left", fontsize=9.5)
    axes[-1].set_xlabel("time the packet was generated (s)")
    fig.suptitle(f"Per-packet one-way latency, {label} (dashed line = 150 ms deadline)", x=0.01, ha="left", fontsize=11)
    save(fig, "fig5_latency_timeline.png")


def cdf(tag, label):
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for m in MODES:
        rows = read(os.path.join("packets", f"{tag}_{m}.csv"))
        n = len(rows)
        ys = sorted(float(r["latency_ms"]) for r in rows if r["delivered"] == "1")
        ax.step(ys, [(i + 1) / n * 100 for i in range(len(ys))], where="post", color=COL[m], lw=2, label=NAME[m])
    ax.axvline(DEADLINE, color=INK2, ls="--", lw=1)
    ax.set_xscale("log")
    ax.set_xlabel("one-way latency (ms, log scale)")
    ax.set_ylabel("% of all packets delivered by then")
    ax.set_title(f"Latency CDF, {label}", loc="left", fontsize=11)
    ax.legend(fontsize=8, loc="lower right")
    save(fig, "fig6_latency_cdf.png")


def cwnd(tag, label):
    rows = read(os.path.join("packets", f"{tag}_cwnd.csv"))
    fig, ax = plt.subplots(figsize=(9, 2.8))
    ax.step([float(r["time_s"]) for r in rows], [float(r["cwnd"]) for r in rows], where="post", color=COL["tcp"], lw=1.5)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("cwnd (segments)")
    ax.set_title(f"TCP congestion window, {label} (drops to 1 on every RTO timeout)", loc="left", fontsize=11)
    save(fig, "fig7_tcp_cwnd.png")


def main():
    os.makedirs(OUT, exist_ok=True)
    topology()
    sc = read("scenarios.csv")
    grouped_bars(sc, "on_time_pct", "packets played on time (%)",
                 "Packets that arrived within the 150 ms deadline", "fig2_on_time.png")
    grouped_bars(sc, "lat_p95_ms", "95th percentile latency (ms, log)",
                 "95th percentile one-way latency", "fig3_p95_latency.png", logy=True,
                 hline=(DEADLINE, "150 ms deadline"))
    grouped_bars(sc, "longest_freeze_ms", "longest freeze (ms)",
                 "Longest video freeze (consecutive packets lost or late)", "fig4_freeze.png")
    tag, label = "congested_wi_fi", "Congested Wi-Fi (5% loss, 35 ms, 12 ms jitter)"
    timeline(tag, label)
    cdf(tag, label)
    cwnd(tag, label)
    sw = read("loss_sweep.csv")
    sweep_lines(sw, "on_time_pct", "packets on time (%)", "On-time delivery vs packet loss", "fig8_sweep_on_time.png")
    sweep_lines(sw, "lat_p95_ms", "p95 latency (ms, log)", "95th percentile latency vs packet loss",
                "fig9_sweep_p95.png", hline=(DEADLINE, "150 ms deadline"), logy=True)


if __name__ == "__main__":
    main()
