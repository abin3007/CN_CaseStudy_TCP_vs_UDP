"""
transports.py - three ways to carry a real-time media stream over UDP sockets.

  1. "udp"   Plain UDP (what RTP/WebRTC media does): fire and forget, every
             packet is played as soon as it arrives, lost packets stay lost.

  2. "tcp"   A TCP-style reliable, in-order transport built on top of UDP:
             sliding window, cumulative ACKs, RTT estimation and RTO from
             RFC 6298, slow start / congestion avoidance, fast retransmit,
             limited transmit (RFC 3042) and NewReno fast recovery
             (RFC 5681 / RFC 6582). Data is handed to
             the application strictly in order, so one lost packet holds up
             all the packets behind it (head-of-line blocking).

  3. "fec"   UDP + Forward Error Correction: after every K data packets one
             XOR parity packet is sent. Any single loss inside a group of K can
             be rebuilt at the receiver without waiting for a retransmission.

Each media packet carries its sequence number and the time it was generated,
so the receiver can measure one-way latency exactly (sender, router and
receiver share one clock because they run on the same machine).

Packet types on the wire (first byte):
  b'D' data   : tx_ts(double) | body
  b'A' ack    : next_expected_seq(uint32) | echoed tx_ts(double)
  b'P' parity : group_id(uint32) | XOR of the K bodies in the group
  body        : seq(uint32) | gen_ts(double) | padding up to PAYLOAD bytes
"""

import select
import socket
import struct
import threading
import time

BODY_HDR = struct.Struct("!Id")
DATA_HDR = struct.Struct("!d")
ACK = struct.Struct("!Id")
PAR_HDR = struct.Struct("!I")


def make_body(seq, gen_ts, payload):
    hdr = BODY_HDR.pack(seq, gen_ts)
    return hdr + b"\x00" * (payload - len(hdr))


def xor_bytes(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def udp_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
    s.bind(("127.0.0.1", 0))
    return s


# ====================================================================== #
#  Receiver (one class handles all three modes)                          #
# ====================================================================== #
class Receiver(threading.Thread):
    def __init__(self, mode, fec_k=4):
        super().__init__(daemon=True)
        self.mode = mode
        self.k = fec_k
        self.sock = udp_socket()
        self.addr = self.sock.getsockname()
        self.running = True
        self.delivered = {}          # seq -> app delivery time
        self.arrivals = 0
        self.rebuilt = set()         # seqs rebuilt from FEC parity
        self.arrived = set()         # seqs that physically arrived
        # tcp state
        self.rcv_nxt = 0
        self.ooo = {}                # out-of-order buffer seq -> gen_ts
        # fec state
        self.groups = {}             # group -> {seq: body}
        self.parity = {}             # group -> parity body

    def _deliver(self, seq, now):
        if seq not in self.delivered:
            self.delivered[seq] = now

    def _fec_try_recover(self, g, now):
        have = self.groups.get(g, {})
        par = self.parity.get(g)
        if par is None or len(have) != self.k - 1:
            return
        rebuilt = par
        for body in have.values():
            rebuilt = xor_bytes(rebuilt, body)
        seq, _gen = BODY_HDR.unpack_from(rebuilt)
        if g * self.k <= seq < (g + 1) * self.k and seq not in have:
            have[seq] = rebuilt
            self.rebuilt.add(seq)
            self._deliver(seq, now)

    def run(self):
        self.sock.settimeout(0.1)
        while self.running:
            try:
                pkt, src = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            now = time.monotonic()
            kind = pkt[:1]
            if kind == b"D":
                self.arrivals += 1
                (tx_ts,) = DATA_HDR.unpack_from(pkt, 1)
                body = pkt[1 + DATA_HDR.size:]
                seq, gen_ts = BODY_HDR.unpack_from(body)
                self.arrived.add(seq)
                if self.mode == "udp":
                    self._deliver(seq, now)
                elif self.mode == "fec":
                    self._deliver(seq, now)
                    g = seq // self.k
                    self.groups.setdefault(g, {})[seq] = body
                    self._fec_try_recover(g, now)
                else:  # tcp: in-order delivery + cumulative ACK
                    if seq == self.rcv_nxt:
                        self._deliver(seq, now)
                        self.rcv_nxt += 1
                        while self.rcv_nxt in self.ooo:
                            self.ooo.pop(self.rcv_nxt)
                            self._deliver(self.rcv_nxt, now)
                            self.rcv_nxt += 1
                    elif seq > self.rcv_nxt:
                        self.ooo[seq] = gen_ts
                    self.sock.sendto(b"A" + ACK.pack(self.rcv_nxt, tx_ts), src)
            elif kind == b"P" and self.mode == "fec":
                (g,) = PAR_HDR.unpack_from(pkt, 1)
                self.parity[g] = pkt[1 + PAR_HDR.size:]
                self._fec_try_recover(g, now)

    @property
    def recovered(self):
        """Packets that were really lost on the link and rebuilt by FEC."""
        return len(self.rebuilt - self.arrived)

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass


# ====================================================================== #
#  Senders                                                               #
# ====================================================================== #
class MediaSource:
    """Generates one media packet every `interval` seconds (constant bit rate),
    like a voice/video codec producing frames at a fixed rate."""

    def __init__(self, rate_pps, duration):
        self.interval = 1.0 / rate_pps
        self.total = int(rate_pps * duration)
        self.t0 = None
        self.made = 0

    def start(self):
        self.t0 = time.monotonic()

    def due(self, now):
        """Return list of (seq, gen_ts) that the codec has produced by `now`."""
        out = []
        while self.made < self.total:
            t = self.t0 + self.made * self.interval
            if t > now:
                break
            out.append((self.made, t))
            self.made += 1
        return out

    def next_time(self):
        if self.made >= self.total:
            return None
        return self.t0 + self.made * self.interval

    def done(self):
        return self.made >= self.total


def run_udp_sender(dst, src, payload, fec_k=0):
    """Plain UDP (fec_k=0) or UDP+XOR-FEC sender."""
    sock = udp_socket()
    stats = {"data_sent": 0, "parity_sent": 0, "retx": 0, "bytes_sent": 0, "timeouts": 0, "fast_retx": 0}
    src.start()
    acc, acc_n = None, 0
    while not src.done():
        nt = src.next_time()
        wait = nt - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        for seq, gen in src.due(time.monotonic()):
            body = make_body(seq, gen, payload)
            pkt = b"D" + DATA_HDR.pack(time.monotonic()) + body
            sock.sendto(pkt, dst)
            stats["data_sent"] += 1
            stats["bytes_sent"] += len(pkt)
            if fec_k:
                acc = body if acc is None else xor_bytes(acc, body)
                acc_n += 1
                if acc_n == fec_k:
                    ppkt = b"P" + PAR_HDR.pack(seq // fec_k) + acc
                    sock.sendto(ppkt, dst)
                    stats["parity_sent"] += 1
                    stats["bytes_sent"] += len(ppkt)
                    acc, acc_n = None, 0
    sock.close()
    return stats


class TCPLikeSender:
    """Reliable in-order sender with TCP congestion control (NewReno style).

    Sequence numbers count packets (segments) rather than bytes, which keeps
    the code readable without changing the behaviour being studied.
    """

    MIN_RTO = 0.2      # Linux uses 200 ms as minimum RTO
    MAX_RTO = 60.0
    INIT_RTO = 1.0     # RFC 6298

    def __init__(self, dst, src, payload, drain_s=5.0):
        self.dst, self.src, self.payload = dst, src, payload
        self.sock = udp_socket()
        self.drain_s = drain_s
        self.buf = {}          # seq -> body (generated, not yet acked)
        self.snd_una = 0
        self.snd_nxt = 0
        self.cwnd = 1.0 * 10   # RFC 6928 initial window of 10 segments
        self.ssthresh = 64.0
        self.dupacks = 0
        self.in_recovery = False
        self.recover = 0
        self.srtt = None
        self.rttvar = None
        self.rto = self.INIT_RTO
        self.timer = None      # absolute expiry time
        self.stats = {"data_sent": 0, "parity_sent": 0, "retx": 0, "bytes_sent": 0,
                      "timeouts": 0, "fast_retx": 0}
        self.cwnd_trace = []   # (time, cwnd) for plotting
        self.high_sent = 0     # highest seq ever sent + 1 (to count retransmissions)

    # -------------------------------------------------------------- #
    def _xmit(self, seq, retx=False):
        retx = retx or seq < self.high_sent
        self.high_sent = max(self.high_sent, seq + 1)
        pkt = b"D" + DATA_HDR.pack(time.monotonic()) + self.buf[seq]
        self.sock.sendto(pkt, self.dst)
        self.stats["data_sent"] += 1
        self.stats["bytes_sent"] += len(pkt)
        if retx:
            self.stats["retx"] += 1
        if self.timer is None:
            self.timer = time.monotonic() + self.rto

    def _flight(self):
        return self.snd_nxt - self.snd_una

    def _try_send_new(self):
        while self.snd_nxt in self.buf and self._flight() < int(self.cwnd):
            self._xmit(self.snd_nxt)
            self.snd_nxt += 1

    def _rtt_sample(self, r):
        # RFC 6298 section 2
        if self.srtt is None:
            self.srtt, self.rttvar = r, r / 2
        else:
            self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - r)
            self.srtt = 0.875 * self.srtt + 0.125 * r
        self.rto = min(self.MAX_RTO, max(self.MIN_RTO, self.srtt + 4 * self.rttvar))

    def _on_ack(self, ack, echo_ts, now):
        self._rtt_sample(now - echo_ts)
        if ack > self.snd_una:                       # new data acknowledged
            newly = ack - self.snd_una
            for s in range(self.snd_una, ack):
                self.buf.pop(s, None)
            self.snd_una = ack
            if self.snd_nxt < self.snd_una:
                self.snd_nxt = self.snd_una
            self.dupacks = 0
            if self.in_recovery:
                if ack >= self.recover:              # full ACK: leave recovery
                    self.in_recovery = False
                    self.cwnd = self.ssthresh
                else:                                # partial ACK (NewReno)
                    self._xmit(self.snd_una, retx=True)
                    self.cwnd = max(1.0, self.cwnd - newly + 1)
            elif self.cwnd < self.ssthresh:
                self.cwnd += newly                   # slow start
            else:
                self.cwnd += newly / self.cwnd       # congestion avoidance
            self.timer = (now + self.rto) if self._flight() > 0 else None
        elif ack == self.snd_una and self._flight() > 0:  # duplicate ACK
            self.dupacks += 1
            if self.dupacks < 3 and not self.in_recovery:
                # RFC 3042 limited transmit: send one new segment per dup ACK
                # so small windows can still produce 3 dup ACKs
                if self.snd_nxt in self.buf:
                    self._xmit(self.snd_nxt)
                    self.snd_nxt += 1
            elif self.dupacks == 3 and not self.in_recovery:
                self.ssthresh = max(self._flight() / 2.0, 2.0)
                self.cwnd = self.ssthresh + 3
                self.in_recovery = True
                self.recover = self.snd_nxt
                self.stats["fast_retx"] += 1
                self._xmit(self.snd_una, retx=True)
            elif self.in_recovery:
                self.cwnd += 1                       # window inflation
        self.cwnd_trace.append((now, self.cwnd))

    def _on_timeout(self, now):
        self.stats["timeouts"] += 1
        self.ssthresh = max(self._flight() / 2.0, 2.0)
        self.cwnd = 1.0
        self.in_recovery = False
        self.dupacks = 0
        self.rto = min(self.MAX_RTO, self.rto * 2)   # exponential back-off
        self.snd_nxt = self.snd_una + 1              # go back to first unacked
        self.timer = None
        self._xmit(self.snd_una, retx=True)
        self.cwnd_trace.append((now, self.cwnd))

    def run(self):
        src = self.src
        src.start()
        end_by = None
        while True:
            now = time.monotonic()
            for seq, gen in src.due(now):
                self.buf[seq] = make_body(seq, gen, self.payload)
            self._try_send_new()
            if src.done():
                if end_by is None:
                    end_by = now + self.drain_s
                if not self.buf or now > end_by:
                    break
            # wait for whichever comes first: an ACK, the next codec frame, the RTO
            deadlines = [t for t in (src.next_time(), self.timer) if t is not None]
            wait = max(0.0, min(deadlines) - now) if deadlines else 0.05
            r, _, _ = select.select([self.sock], [], [], min(wait, 0.05))
            now = time.monotonic()
            if r:
                while True:
                    try:
                        self.sock.setblocking(False)
                        pkt = self.sock.recv(2048)
                    except (BlockingIOError, OSError):
                        break
                    if pkt[:1] == b"A":
                        ack, echo = ACK.unpack_from(pkt, 1)
                        self._on_ack(ack, echo, now)
                self.sock.setblocking(True)
            if self.timer is not None and now >= self.timer:
                self._on_timeout(now)
        self.sock.close()
        return self.stats
