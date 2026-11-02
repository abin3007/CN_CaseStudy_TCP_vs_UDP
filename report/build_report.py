import csv, os
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
G = ROOT + "/graphs/"
REPO = "https://github.com/abin3007/CN_CaseStudy_TCP_vs_UDP"

sc = list(csv.DictReader(open(ROOT + "/results/scenarios.csv")))
sw = list(csv.DictReader(open(ROOT + "/results/loss_sweep.csv")))
def S(scen, mode, k):
    return next(r for r in sc if r["scenario"] == scen and r["mode"] == mode)[k]
def W(loss, mode, k):
    return next(r for r in sw if float(r["loss_pct"]) == loss and r["mode"] == mode)[k]

doc = Document()
sec = doc.sections[0]
sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
for side in ("left_margin", "right_margin"):
    setattr(sec, side, Cm(2.0))
sec.top_margin = sec.bottom_margin = Cm(1.8)
st = doc.styles["Normal"]
st.font.name = "Calibri"
st.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
st.font.size = Pt(10.5)
st.paragraph_format.space_after = Pt(4)
st.paragraph_format.line_spacing = 1.1

def para(text="", bold_lead=None, align=None, size=None, italic=False, after=None):
    p = doc.add_paragraph()
    if bold_lead:
        r = p.add_run(bold_lead + " ")
        r.bold = True
        if size: r.font.size = Pt(size)
    r = p.add_run(text)
    r.italic = italic
    if size: r.font.size = Pt(size)
    if align == "c": p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == "j" or align is None: p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if after is not None: p.paragraph_format.space_after = Pt(after)
    return p

def head(text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text); r.bold = True; r.font.size = Pt(12.5)
    r.font.color.rgb = RGBColor(0x1c, 0x3d, 0x6b)
    return p

def bullet(text, lead=None):
    p = doc.add_paragraph(style="List Bullet")
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if lead:
        p.add_run(lead + " ").bold = True
    p.add_run(text)
    p.paragraph_format.space_after = Pt(2)
    return p

def shade(cell, hexcol):
    tcPr = cell._tc.get_or_add_tcPr()
    s = OxmlElement("w:shd"); s.set(qn("w:val"), "clear"); s.set(qn("w:color"), "auto"); s.set(qn("w:fill"), hexcol)
    tcPr.append(s)

def table(rows, widths=None, size=8.5, header=True):
    t = doc.add_table(rows=len(rows), cols=len(rows[0]))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            c = t.cell(i, j)
            c.text = ""
            p = c.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(str(v)); r.font.size = Pt(size)
            if i == 0 and header:
                r.bold = True; shade(c, "DCE8F7")
            if widths: c.width = Cm(widths[j])
    if widths:
        t.autofit = False
        grid = t._tbl.tblGrid
        for j, gc in enumerate(grid.findall(qn("w:gridCol"))):
            gc.set(qn("w:w"), str(int(widths[j] * 567)))
        tblPr = t._tbl.tblPr
        tw = OxmlElement("w:tblW"); tw.set(qn("w:w"), str(int(sum(widths) * 567))); tw.set(qn("w:type"), "dxa")
        for old in tblPr.findall(qn("w:tblW")):
            tblPr.remove(old)
        tblPr.append(tw)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t

def fig(path, caption, width=16.5):
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(G + path, width=Cm(width))
    p.paragraph_format.space_after = Pt(0)
    c = para(caption, align="c", size=9, italic=True, after=6)

# ------------------------------------------------------------------ header
p = para("", align="c", after=0); r = p.add_run("Case Study: TCP vs UDP for Real-Time Video Calls over Lossy Wi-Fi"); r.bold = True; r.font.size = Pt(15)
p = para("", align="c", after=0); r = p.add_run("Computer Networks (BACSE203) – Transport Layer Case Study"); r.font.size = Pt(11)
para("Team members: [Your Name] [Register No.] | Date: 02/11/2026", align="c", after=0)
para("Code and data: " + REPO, align="c", after=8)

# ------------------------------------------------------------------ 1
head("1. Problem statement")
para("Since online classes became normal, students and teachers use Zoom, Google Meet, Microsoft Teams and WhatsApp calls every day, very often over a crowded campus or hostel Wi-Fi network or over weak 4G. The common complaint is not that the connection is \"slow\": a 400 kbit/s video call needs far less bandwidth than these networks offer. The complaint is that the video freezes, the voice cuts out and people talk over each other. The real cause is packet loss, delay and jitter on the wireless link, and how the transport layer reacts to them.")
para("TCP and UDP react in opposite ways. TCP guarantees that every byte arrives and in order, by retransmitting lost segments and slowing down when it sees loss. UDP gives no guarantee at all. For a file download TCP is clearly right. For a live call, a packet that arrives after it should have been played is as useless as a lost one. This case study asks the question that a network or application designer has to answer: which transport gives the best live call on a lossy Wi-Fi network, and can we do better than both?")
para("Objective and tangible outcome. We built a network emulator and three working transports in Python, sent the same video-call stream through six realistic network conditions and a loss sweep, and produced a protocol comparison with performance tables, per-packet latency graphs and a TCP congestion-window trace (Sections 4 and 5).")

# ------------------------------------------------------------------ 2
head("2. Background")
bullet("Connection-oriented and reliable. Each segment carries a sequence number; the receiver returns a cumulative ACK. A lost segment is retransmitted after three duplicate ACKs (fast retransmit) or after the retransmission timeout (RTO). The RTO is computed from smoothed RTT and RTT variance (RFC 6298): RTO = SRTT + 4·RTTVAR, minimum 200 ms in Linux. Each timeout doubles the RTO (exponential back-off). Data is given to the application strictly in order, so a single missing segment holds back every later segment that has already arrived. This is head-of-line (HOL) blocking. Congestion control (slow start, congestion avoidance, fast recovery; RFC 5681) halves the window on loss and resets it to 1 segment on a timeout.", "TCP.")
bullet("Connectionless, no ACKs, no retransmission, no ordering, 8-byte header. Real-time media protocols (RTP, WebRTC, VoIP) run on UDP and let the application decide what to do about loss: usually play what arrives and hide small gaps (packet loss concealment).", "UDP.")
bullet("The sender adds redundant data so that the receiver can rebuild lost packets without asking for a retransmission. The simplest form, used here, sends one XOR parity packet after every K = 4 data packets; any single loss in a group of 4 can be recovered. WebRTC uses the same idea (ULPFEC/FlexFEC, RFC 5109 / RFC 8627).", "Forward Error Correction (FEC).")
bullet("ITU-T G.114 recommends that one-way mouth-to-ear delay stays below 150 ms for good interactive conversation. We use 150 ms as the playout deadline: a packet that arrives later than 150 ms after it was generated cannot be played.", "Deadline.")
bullet("For TCP the Mathis et al. model gives the maximum steady throughput as roughly (MSS/RTT)·1.22/√p, where p is the loss rate. If this is below the bit rate of the call, TCP cannot keep up and data piles up in the send buffer.", "TCP throughput under loss.")

# ------------------------------------------------------------------ 3
head("3. Setup and method")
para("All three transports exchange real UDP datagrams over the loopback interface of one computer (Python 3.11, Linux; the code also runs on Windows and macOS). Between sender and receiver sits our own impairment emulator, netemu.py, which acts like a lossy Wi-Fi access point or router (Graph 1). We wrote it instead of using Linux tc netem so that the experiment needs no administrator rights and works on any OS.")
fig("fig1_topology.png", "Graph 1. Experimental topology. Data and ACKs both pass through the impaired link.", 15.5)
bullet("Drops packets with probability p (Bernoulli), or in bursts using a two-state Gilbert-Elliott model (average loss p, mean burst length 3 packets) to imitate Wi-Fi fading and interference. Adds a fixed one-way delay plus Gaussian jitter. Like a real Wi-Fi link it keeps packets in order (FIFO). Both directions are impaired, so TCP ACKs can be lost too.", "Impaired link (netemu.py).")
bullet("A constant-bit-rate codec: one 1000-byte packet every 20 ms (50 packets/s, 400 kbit/s, similar to a standard-definition video call or RTP audio framing). Every packet carries its sequence number and generation timestamp, so one-way latency is measured exactly (all parts share one clock).", "Media source.")
bullet("Implemented on top of UDP with packet-based sequence numbers: sliding window, cumulative ACKs, RFC 6298 RTT estimation and RTO (minimum 200 ms, back-off ×2), initial window 10, slow start, congestion avoidance, fast retransmit after 3 duplicate ACKs, limited transmit (RFC 3042) and NewReno fast recovery (RFC 6582). The receiver delivers strictly in order. ACKs echo the sender timestamp, like the TCP timestamp option.", "TCP (reliable, in-order).")
bullet("Sends each packet once; the receiver plays whatever arrives.", "UDP (plain).")
bullet("Plain UDP plus one XOR parity packet per 4 data packets (25 % extra payload).", "UDP + FEC.")
para("Each run lasts 20 s (1,000 media packets) and is repeated for every transport under the six conditions in Table 1, which were chosen to match published Wi-Fi and mobile measurements, and for a loss sweep from 0 % to 15 % (25 ms delay, 5 ms jitter). Loss models use a fixed random seed so all three transports see the same network. Every run writes a per-packet CSV log (sequence number, generation time, delivery time, latency); the summary metrics are calculated from these logs by experiment.py and the graphs by plots.py.")
table([["Scenario", "Loss", "One-way delay", "Jitter (σ)", "Loss pattern", "Approx. RTT"],
       ["Wired LAN", "0 %", "2 ms", "0.5 ms", "–", "4 ms"],
       ["Good Wi-Fi", "1 %", "15 ms", "3 ms", "random", "30 ms"],
       ["Busy campus Wi-Fi", "3 %", "25 ms", "8 ms", "random", "50 ms"],
       ["Congested Wi-Fi", "5 %", "35 ms", "12 ms", "random", "70 ms"],
       ["Weak 4G / mobile", "10 %", "50 ms", "15 ms", "random", "100 ms"],
       ["Bursty Wi-Fi (fading)", "5 %", "25 ms", "8 ms", "bursts, mean 3 pkts", "50 ms"]],
      widths=[4.2, 1.4, 2.4, 2, 3.4, 2.3])
para("Table 1. Network scenarios (loss and delay apply in each direction).", align="c", size=9, italic=True)
para("Metrics. On-time % = packets that reached the receiver within 150 ms, out of all packets generated (this is what the viewer actually sees). Latency mean/median/95th/99th percentile/maximum. Jitter with the RFC 3550 RTP estimator J = J + (|D| − J)/16. Longest freeze = longest run of consecutive packets that were lost or late, × 20 ms. Overhead = extra bytes on the wire (headers, retransmissions, parity) relative to the payload. For TCP we also count retransmissions, RTO timeouts and fast retransmits and record the congestion window.")

# ------------------------------------------------------------------ 4
head("4. Results")
modes = [("tcp", "TCP"), ("udp", "UDP"), ("fec", "UDP+FEC")]
rows = [["Scenario", "Transport", "Delivered %", "On-time %", "Median (ms)", "p95 (ms)", "p99 (ms)", "Jitter (ms)", "Longest freeze (ms)", "Overhead %"]]
for name in [r["scenario"] for r in sc][::3]:
    for m, lab in modes:
        rows.append([name if m == "tcp" else "", lab, S(name, m, "delivery_pct"), S(name, m, "on_time_pct"),
                     S(name, m, "lat_p50_ms"), S(name, m, "lat_p95_ms"), S(name, m, "lat_p99_ms"),
                     S(name, m, "jitter_ms_rfc3550"), S(name, m, "longest_freeze_ms"), S(name, m, "overhead_pct")])
table(rows, widths=[3.0, 1.6, 1.5, 1.5, 1.5, 1.4, 1.4, 1.4, 1.8, 1.5], size=7.5)
para("Table 2. Main results, 1,000 packets per run. Latency is one-way, from generation to delivery to the application.", align="c", size=9, italic=True)

rows = [["Scenario", "Data drops on link", "ACK drops", "Retransmissions", "Fast retransmits", "RTO timeouts", "On-time goodput (kbit/s)"]]
for name in [r["scenario"] for r in sc][::3]:
    rows.append([name, S(name, "tcp", "link_fwd_drops"), S(name, "tcp", "link_rev_drops"), S(name, "tcp", "retransmissions"),
                 S(name, "tcp", "fast_retransmits"), S(name, "tcp", "rto_timeouts"), S(name, "tcp", "goodput_kbps")])
table(rows, widths=[3.8, 2.2, 1.7, 2.2, 2.2, 2.0, 2.8], size=8)
para("Table 3. TCP internals per scenario (target goodput is 400 kbit/s).", align="c", size=9, italic=True)

fig("fig2_on_time.png", "Graph 2. Share of packets that reached the receiver within the 150 ms deadline.")
fig("fig3_p95_latency.png", "Graph 3. 95th percentile one-way latency (log scale). Dashed line: 150 ms deadline.")
fig("fig5_latency_timeline.png", "Graph 4. Latency of every packet in the Congested Wi-Fi run. Crosses mark packets that never arrived.")
fig("fig6_latency_cdf.png", "Graph 5. Latency CDF in Congested Wi-Fi; curves end below 100 % where packets were lost.", 12)
fig("fig7_tcp_cwnd.png", "Graph 6. TCP congestion window in Congested Wi-Fi.")
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.add_run().add_picture(G + "fig8_sweep_on_time.png", width=Cm(7.7))
p.add_run(" ")
p.add_run().add_picture(G + "fig9_sweep_p95.png", width=Cm(7.7))
para("Graph 7. Loss sweep at 25 ms delay, 5 ms jitter: (a) on-time delivery, (b) 95th percentile latency.", align="c", size=9, italic=True)

rows = [["Loss on link", "TCP on-time %", "TCP p95 (ms)", "UDP on-time %", "UDP+FEC on-time %", "UDP+FEC p95 (ms)"]]
for l in [0.0, 1.0, 2.0, 4.0, 6.0, 8.0, 10.0, 15.0]:
    rows.append([f"{l:g} %", W(l, "tcp", "on_time_pct"), W(l, "tcp", "lat_p95_ms"), W(l, "udp", "on_time_pct"),
                 W(l, "fec", "on_time_pct"), W(l, "fec", "lat_p95_ms")])
table(rows, widths=[2.4, 2.6, 2.6, 2.6, 3.0, 3.0], size=8)
para("Table 4. Loss sweep.", align="c", size=9, italic=True)

# ------------------------------------------------------------------ 5
head("5. Analysis: answers to the key questions")
para(f"With no loss (Wired LAN) all three transports are identical: 100 % on time, median {S('Wired LAN','tcp','lat_p50_ms')} ms. With 1 % loss (Good Wi-Fi) TCP still plays everything on time, because its retransmissions arrive within the 150 ms budget, although its p99 latency rises to {S('Good Wi-Fi','tcp','lat_p99_ms')} ms compared with {S('Good Wi-Fi','udp','lat_p99_ms')} ms for UDP. Plain UDP loses exactly the 1 % that the link drops, and FEC repairs all of them.", "Q1. Which transport gives the best call on a good network?")
para(f"From 3 % loss onwards TCP gets worse much faster than the loss rate. In Congested Wi-Fi (5 % loss) TCP delivers 100 % of the data but only {S('Congested Wi-Fi','tcp','on_time_pct')} % of it in time; its median latency is {S('Congested Wi-Fi','tcp','lat_p50_ms')} ms and the longest freeze is {int(S('Congested Wi-Fi','tcp','longest_freeze_ms'))/1000:.2f} s. Plain UDP plays {S('Congested Wi-Fi','udp','on_time_pct')} % with a median of {S('Congested Wi-Fi','udp','lat_p50_ms')} ms and never freezes for more than {S('Congested Wi-Fi','udp','longest_freeze_ms')} ms. On Weak 4G TCP collapses completely: {S('Weak 4G / mobile','tcp','on_time_pct')} % on time, median {float(S('Weak 4G / mobile','tcp','lat_p50_ms'))/1000:.1f} s, i.e. the call is unusable, while UDP still plays {S('Weak 4G / mobile','udp','on_time_pct')} %. The loss sweep (Graph 7, Table 4) shows the same cliff: TCP is fine up to about 2 %, drops to {W(6.0,'tcp','on_time_pct')} % on time at 6 % loss and {W(15.0,'tcp','on_time_pct')} % at 15 %, while UDP falls only linearly with the loss rate.", "Q2. What happens as loss increases?")
para(f"Three TCP mechanisms combine. (1) Head-of-line blocking: in Graph 4 every TCP loss produces a 'sawtooth' – the lost packet waits for its retransmission and all packets behind it wait too, then they are released at once with steadily falling latency. (2) Retransmission timeouts: when a loss cannot be detected by three duplicate ACKs (small window, lost retransmission or lost ACKs) TCP waits for the RTO, at least 200 ms and doubled on each repeat; there were {S('Congested Wi-Fi','tcp','rto_timeouts')} timeouts in Congested Wi-Fi and {S('Weak 4G / mobile','tcp','rto_timeouts')} on Weak 4G. A single RTO alone exceeds the whole 150 ms budget. (3) Congestion control misreads wireless loss as congestion: Graph 6 shows the window halved on every fast retransmit and reset to 1 on every timeout, although the link is not congested at all. When the window is small TCP sends less than the 50 packets/s the codec produces, so data queues in the send buffer and the delay keeps growing. The Mathis model predicts this: with RTT ≈ 100 ms and p = 0.10 on Weak 4G, 1.22/(0.1·√0.1) ≈ 39 packets/s, which is below the 50 packets/s the call needs, so the backlog can never drain (median latency {float(S('Weak 4G / mobile','tcp','lat_p50_ms'))/1000:.1f} s, on-time goodput {S('Weak 4G / mobile','tcp','goodput_kbps')} kbit/s out of 400). At 5 % loss and 70 ms RTT the limit is about 78 packets/s, close enough to 50 that timeouts push TCP below it for long periods.", "Q3. Why is TCP so much worse when it delivers more data?")
para(f"Yes, for random loss. With one parity packet per four data packets, FEC rebuilt {S('Congested Wi-Fi','fec','fec_recovered')} lost packets in Congested Wi-Fi and {S('Weak 4G / mobile','fec','fec_recovered')} on Weak 4G, raising on-time delivery from {S('Congested Wi-Fi','udp','on_time_pct')} % to {S('Congested Wi-Fi','fec','on_time_pct')} % and from {S('Weak 4G / mobile','udp','on_time_pct')} % to {S('Weak 4G / mobile','fec','on_time_pct')} %, with only a small latency cost (p95 {S('Congested Wi-Fi','fec','lat_p95_ms')} ms vs {S('Congested Wi-Fi','udp','lat_p95_ms')} ms, because a rebuilt packet must wait for the parity packet at the end of its group). In the loss sweep FEC keeps on-time delivery above 97 % up to 10 % loss. The cost is a fixed 25 % payload overhead ({S('Congested Wi-Fi','fec','overhead_pct')} % on the wire) – but TCP also spent {S('Weak 4G / mobile','tcp','overhead_pct')} % extra on retransmissions on Weak 4G and still failed.", "Q4. Does FEC fix the problem?")
para(f"Not much. With the same 5 % average loss arriving in bursts (Bursty Wi-Fi), FEC only improves on-time delivery from {S('Bursty Wi-Fi (fading)','udp','on_time_pct')} % to {S('Bursty Wi-Fi (fading)','fec','on_time_pct')} %, because a burst usually removes two or more packets from one group of four, and a single XOR parity can rebuild only one. The longest freezes for UDP and FEC ({S('Bursty Wi-Fi (fading)','udp','longest_freeze_ms')} and {S('Bursty Wi-Fi (fading)','fec','longest_freeze_ms')} ms) are also longer than with random loss. Real systems handle this with interleaving (spreading consecutive packets over different FEC groups), stronger codes such as Reed-Solomon, or adaptive FEC that adds more parity when bursts are detected. Interestingly TCP did relatively well here ({S('Bursty Wi-Fi (fading)','tcp','on_time_pct')} % on time), because one burst costs it one recovery episode instead of several.", "Q5. What about bursty loss, which is typical of Wi-Fi?")

# ------------------------------------------------------------------ 6
head("6. Recommendations")
bullet("Carry live audio and video over UDP (RTP/WebRTC, or QUIC datagrams), never over plain TCP. TCP is the right choice only for the parts of a call application that must be complete: chat messages, file sharing, signalling and recordings.", "For application designers:")
bullet("Add adaptive FEC on top of UDP and interleave packets across FEC groups so burst losses are spread out. Combine with a jitter buffer and packet loss concealment, and lower the codec bit rate when loss is high instead of retransmitting.", "Make UDP resilient:")
bullet("Wireless loss, not bandwidth, is what breaks calls. Reduce it with more access points at lower transmit power, 5 GHz/6 GHz bands to escape 2.4 GHz interference, and QoS (Wi-Fi WMM / DSCP EF marking) that gives voice and video priority over bulk downloads. Keep one-way delay well under 150 ms.", "For campus network administrators:")
bullet("If a call must fall back to TCP (for example through a firewall that blocks UDP), expect freezes at 3 % loss and more; SACK, RACK-TLP and a smaller minimum RTO in modern stacks reduce but do not remove head-of-line blocking.", "TCP fallback:")

# ------------------------------------------------------------------ 7
head("7. Limitations")
para("The TCP is our own implementation of the standard algorithms over UDP, not the operating system's TCP, and counts segments rather than bytes; it lacks SACK and RACK-TLP, which modern Linux and Windows stacks use and which would reduce timeouts somewhat. The network is emulated on one machine, so there is no real radio, no bandwidth limit and no competing traffic; loss is independent per packet except in the bursty scenario. Each condition was run once for 20 s with a fixed seed; repeating runs with other seeds would give confidence intervals. These simplifications affect the exact numbers but not the main mechanisms, which follow directly from how TCP and UDP are defined.")

# ------------------------------------------------------------------ 8
head("8. Overall interpretation and conclusion")
para(f"The experiment shows clearly why real-time applications do not use TCP for media. On a clean network all three transports behave the same. As soon as the wireless link loses a few percent of its packets, TCP's reliability turns into lateness: head-of-line blocking holds back packets that already arrived, retransmission timeouts of 200 ms or more exceed the 150 ms conversational budget on their own, and congestion control treats random wireless loss as congestion and cuts the sending rate below the rate of the call. At 5 % loss TCP delivered everything but played only {S('Congested Wi-Fi','tcp','on_time_pct')} % in time, and on weak 4G the call failed completely. Plain UDP degraded gracefully, losing about as many packets as the link dropped while keeping latency near the propagation delay. UDP with simple XOR FEC gave the best result in every lossy random-loss scenario (≥ 96.8 % on time up to 10 % loss) for a fixed 25 % overhead, but needs interleaving or stronger codes to cope with bursty Wi-Fi loss. The answer to the real-world problem is therefore: run live calls over UDP with adaptive FEC, and on the network side reduce wireless loss and prioritise real-time traffic, because for interactive media a late packet is a lost packet.")

head("References")
for ref in [
    "J. Postel, \"User Datagram Protocol,\" RFC 768, 1980;  W. Eddy (ed.), \"Transmission Control Protocol,\" RFC 9293, 2022.",
    "M. Allman, V. Paxson, E. Blanton, \"TCP Congestion Control,\" RFC 5681, 2009;  RFC 6582 (NewReno), RFC 3042 (Limited Transmit).",
    "V. Paxson, M. Allman, J. Chu, M. Sargent, \"Computing TCP's Retransmission Timer,\" RFC 6298, 2011.",
    "H. Schulzrinne et al., \"RTP: A Transport Protocol for Real-Time Applications,\" RFC 3550, 2003.",
    "A. Li, \"RTP Payload Format for Generic Forward Error Correction,\" RFC 5109, 2007;  RFC 8627 (FlexFEC).",
    "ITU-T Recommendation G.114, \"One-way transmission time,\" 2003.",
    "M. Mathis, J. Semke, J. Mahdavi, T. Ott, \"The Macroscopic Behavior of the TCP Congestion Avoidance Algorithm,\" ACM SIGCOMM CCR, 1997.",
    "J. Kurose, K. Ross, Computer Networking: A Top-Down Approach, 8th ed., Pearson, 2021 (Ch. 3 Transport Layer, Ch. 9 Multimedia Networking).",
]:
    bullet(ref)

out = ROOT + "/report/CN_CaseStudy_TCP_vs_UDP_Report.docx"
doc.save(out)
print(out)
