"""
experiment.py - run TCP-style, plain UDP and UDP+FEC media streams through the
impaired link under several real-world network conditions and record the
results.

Usage:
    python experiment.py                 # full study (about 15 minutes)
    python experiment.py --quick         # 5 s per run, for a fast demo
    python experiment.py --mode udp --loss 0.05 --delay 30 --jitter 10   # one run

Outputs (in ../results):
    scenarios.csv     one row per (scenario, transport) with all metrics
    loss_sweep.csv    one row per (loss rate, transport)
    packets/*.csv     per-packet log for every run (seq, gen time, delivery time, latency)
"""

import argparse
import csv
import os
import statistics
import threading
import time

from netemu import ImpairedLink
from transports import MediaSource, Receiver, TCPLikeSender, run_udp_sender

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "..", "results")

# Media stream: 50 packets/s x 1000 B payload = 400 kbit/s, similar to a
# standard-definition video call (one packet every 20 ms, like RTP audio/video).
RATE_PPS = 50
PAYLOAD = 1000
DEADLINE_MS = 150      # ITU-T G.114: one-way delay above 150 ms hurts interactivity
FEC_K = 4              # one parity packet per 4 data packets (25 % overhead)

# Real-world conditions. Delays are one-way, so RTT is about twice the delay.
SCENARIOS = [
    # name,                    loss,  delay, jitter, burst
    ("Wired LAN",              0.00,   2,     0.5,   0),
    ("Good Wi-Fi",             0.01,  15,     3,     0),
    ("Busy campus Wi-Fi",      0.03,  25,     8,     0),
    ("Congested Wi-Fi",        0.05,  35,    12,     0),
    ("Weak 4G / mobile",       0.10,  50,    15,     0),
    ("Bursty Wi-Fi (fading)",  0.05,  25,     8,     3),
]
SWEEP_LOSS = [0.0, 0.01, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15]
SWEEP_DELAY, SWEEP_JITTER = 25, 5
MODES = ["tcp", "udp", "fec"]
MODE_NAME = {"tcp": "TCP (reliable, in-order)", "udp": "UDP (plain)", "fec": "UDP + FEC"}


def percentile(xs, p):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def run_one(mode, loss, delay_ms, jitter_ms, burst=0, duration=20.0, seed=7, tag=None):
    rx = Receiver(mode, fec_k=FEC_K)
    rx.start()
    link = ImpairedLink(rx.addr, loss=loss, delay_ms=delay_ms, jitter_ms=jitter_ms,
                        burst_len=burst, seed=seed)
    link.start()
    dst = ("127.0.0.1", link.port)
    src = MediaSource(RATE_PPS, duration)

    t_start = time.monotonic()
    cwnd_trace = []
    if mode == "tcp":
        snd = TCPLikeSender(dst, src, PAYLOAD)
        stats = snd.run()
        cwnd_trace = snd.cwnd_trace
    else:
        stats = run_udp_sender(dst, src, PAYLOAD, fec_k=FEC_K if mode == "fec" else 0)
    time.sleep(0.5 + 2 * delay_ms / 1000.0)  # let packets in flight arrive
    link.stop()
    rx.stop()

    gen = {s: src.t0 + s * src.interval for s in range(src.total)}
    lat = {s: (rx.delivered[s] - gen[s]) * 1000 for s in rx.delivered if s in gen}
    n = src.total
    lats = [lat[s] for s in sorted(lat)]

    # RFC 3550 inter-arrival jitter over the delivered packets in seq order
    j, prev = 0.0, None
    for s in sorted(lat):
        if prev is not None:
            j += (abs(lat[s] - lat[prev]) - j) / 16.0
        prev = s

    on_time = [s for s in range(n) if s in lat and lat[s] <= DEADLINE_MS]
    # longest freeze: longest run of packets that are lost or too late to play
    longest, run = 0, 0
    ok = set(on_time)
    for s in range(n):
        run = 0 if s in ok else run + 1
        longest = max(longest, run)

    useful_bytes = n * PAYLOAD
    m = {
        "transport": MODE_NAME[mode],
        "mode": mode,
        "loss_pct": round(loss * 100, 1),
        "delay_ms": delay_ms,
        "jitter_ms": jitter_ms,
        "burst": burst,
        "generated": n,
        "delivered": len(lat),
        "delivery_pct": round(100 * len(lat) / n, 2),
        "on_time_pct": round(100 * len(on_time) / n, 2),
        "late_pct": round(100 * (len(lat) - len(on_time)) / n, 2),
        "lost_pct": round(100 * (n - len(lat)) / n, 2),
        "lat_mean_ms": round(statistics.mean(lats), 1) if lats else None,
        "lat_p50_ms": round(percentile(lats, 50), 1),
        "lat_p95_ms": round(percentile(lats, 95), 1),
        "lat_p99_ms": round(percentile(lats, 99), 1),
        "lat_max_ms": round(max(lats), 1) if lats else None,
        "jitter_ms_rfc3550": round(j, 2),
        "longest_freeze_ms": longest * 1000 // RATE_PPS,
        "fec_recovered": rx.recovered,
        "retransmissions": stats["retx"],
        "rto_timeouts": stats["timeouts"],
        "fast_retransmits": stats["fast_retx"],
        "bytes_on_wire": stats["bytes_sent"],
        "overhead_pct": round(100 * (stats["bytes_sent"] - useful_bytes) / useful_bytes, 1),
        "goodput_kbps": round(len(on_time) * PAYLOAD * 8 / duration / 1000, 1),
        "link_fwd_drops": link.stats["fwd_drop"],
        "link_rev_drops": link.stats["rev_drop"],
    }

    if tag:
        os.makedirs(os.path.join(RESULTS, "packets"), exist_ok=True)
        with open(os.path.join(RESULTS, "packets", f"{tag}_{mode}.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["seq", "gen_time_s", "delivered", "latency_ms", "on_time"])
            for s in range(n):
                g = gen[s] - src.t0
                if s in lat:
                    w.writerow([s, f"{g:.3f}", 1, f"{lat[s]:.2f}", int(lat[s] <= DEADLINE_MS)])
                else:
                    w.writerow([s, f"{g:.3f}", 0, "", 0])
        if cwnd_trace:
            with open(os.path.join(RESULTS, "packets", f"{tag}_cwnd.csv"), "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["time_s", "cwnd"])
                for t, c in cwnd_trace:
                    w.writerow([f"{t - t_start:.3f}", f"{c:.2f}"])
    return m


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def slug(name):
    return "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="5 s runs instead of 20 s")
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--mode", choices=MODES)
    ap.add_argument("--loss", type=float, default=0.05)
    ap.add_argument("--delay", type=float, default=25)
    ap.add_argument("--jitter", type=float, default=5)
    ap.add_argument("--burst", type=float, default=0)
    a = ap.parse_args()
    dur = a.duration or (5.0 if a.quick else 20.0)
    os.makedirs(RESULTS, exist_ok=True)

    if a.mode:  # single run
        m = run_one(a.mode, a.loss, a.delay, a.jitter, a.burst, duration=dur)
        for k, v in m.items():
            print(f"{k:>20}: {v}")
        return

    rows = []
    for name, loss, d, jit, burst in SCENARIOS:
        for mode in MODES:
            m = run_one(mode, loss, d, jit, burst, duration=dur, tag=slug(name))
            m = {"scenario": name, **m}
            rows.append(m)
            print(f"{name:24} {m['transport']:26} delivered {m['delivery_pct']:6.2f}%  "
                  f"on-time {m['on_time_pct']:6.2f}%  p95 {m['lat_p95_ms']:7.1f} ms  "
                  f"freeze {m['longest_freeze_ms']:5} ms", flush=True)
    write_csv(os.path.join(RESULTS, "scenarios.csv"), rows)

    rows = []
    for loss in SWEEP_LOSS:
        for mode in MODES:
            m = run_one(mode, loss, SWEEP_DELAY, SWEEP_JITTER, duration=dur, seed=11)
            rows.append(m)
            print(f"sweep loss {loss*100:4.1f}% {m['transport']:26} on-time {m['on_time_pct']:6.2f}%  "
                  f"p95 {m['lat_p95_ms']:7.1f} ms", flush=True)
    write_csv(os.path.join(RESULTS, "loss_sweep.csv"), rows)


if __name__ == "__main__":
    main()
