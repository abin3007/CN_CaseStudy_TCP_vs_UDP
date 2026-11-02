# TCP vs UDP for Real-Time Video Calls over Lossy Wi-Fi

Computer Networks (BACSE203) case study.

**Real-world problem:** online classes and video calls freeze and lag on busy campus Wi-Fi and weak mobile data, even when the connection is "fast enough". This project measures *why*, by sending the same 400 kbit/s video-call stream three ways through an emulated lossy network:

| Transport | How it works | Real-world example |
|---|---|---|
| **TCP (reliable, in-order)** | sliding window, cumulative ACKs, RFC 6298 RTO, slow start, congestion avoidance, fast retransmit, NewReno recovery | video over HTTP/TCP, older meeting apps on TCP fallback |
| **UDP (plain)** | fire and forget, lost packets stay lost | RTP media in VoIP / WebRTC |
| **UDP + FEC** | 1 XOR parity packet per 4 data packets, rebuilds any single loss in a group | WebRTC FlexFEC / ULPFEC, Zoom, Google Meet |

All traffic uses real UDP sockets and passes through `netemu.py`, a user-space "lossy router" that adds packet loss (random or bursty Gilbert-Elliott), propagation delay and jitter in both directions. This works on Windows, macOS and Linux with no admin rights (no `tc netem` needed).

## Project layout

```
src/netemu.py       network impairment emulator (loss, delay, jitter, bursty loss, bottleneck rate)
src/transports.py   the three transports: TCP-style sender, UDP sender, UDP+FEC sender, receiver
src/experiment.py   runs all scenarios and the loss sweep, writes CSVs to results/
src/plots.py        draws every graph in graphs/ from the CSVs
results/            scenarios.csv, loss_sweep.csv, per-packet logs (packets/*.csv), run_log.txt
graphs/             PNG figures used in the report
report/             the case study report (DOCX and PDF)
```

## How to run

Needs Python 3.8+.

```bash
pip install -r requirements.txt
cd src
python experiment.py            # full study, 20 s per run, about 15 minutes
python experiment.py --quick    # 5 s per run, about 4 minutes
python plots.py                 # regenerate graphs from results/
```

A single live demo run (good for a viva):

```bash
python experiment.py --mode tcp --loss 0.05 --delay 35 --jitter 12 --duration 10
python experiment.py --mode udp --loss 0.05 --delay 35 --jitter 12 --duration 10
python experiment.py --mode fec --loss 0.05 --delay 35 --jitter 12 --duration 10
```

## Scenarios

| Scenario | Loss | One-way delay | Jitter (sd) | Loss pattern |
|---|---|---|---|---|
| Wired LAN | 0 % | 2 ms | 0.5 ms | none |
| Good Wi-Fi | 1 % | 15 ms | 3 ms | random |
| Busy campus Wi-Fi | 3 % | 25 ms | 8 ms | random |
| Congested Wi-Fi | 5 % | 35 ms | 12 ms | random |
| Weak 4G / mobile | 10 % | 50 ms | 15 ms | random |
| Bursty Wi-Fi (fading) | 5 % | 25 ms | 8 ms | bursts of 3 packets on average |

Plus a loss sweep from 0 % to 15 % at 25 ms delay and 5 ms jitter.

## Metrics

* **On-time %**: packets that reached the receiver within 150 ms (ITU-T G.114 limit for interactive conversation). A packet that arrives later is useless for a live call.
* **Latency** mean / median / 95th / 99th percentile / max, one-way, per packet.
* **Jitter** using the RFC 3550 (RTP) estimator.
* **Longest freeze**: the longest run of consecutive packets that were lost or late, in ms.
* **Overhead**: extra bytes sent (headers, retransmissions, parity) relative to useful payload.
* TCP internals: retransmissions, RTO timeouts, fast retransmits, congestion window trace.

## Key finding

TCP always delivers 100 % of the data, but on a lossy link many packets arrive too late to be played, because one lost packet blocks every packet behind it until it is retransmitted (head-of-line blocking), and a timeout costs at least 200 ms. Plain UDP keeps latency low but loses packets. UDP + FEC keeps the latency of UDP and repairs most random losses for 25 % extra bandwidth, which is why real video-call systems use it. See the report for the full numbers.
