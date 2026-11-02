"""
netemu.py - a small user-space network impairment emulator ("lossy router").

It is a UDP relay that sits between a sender and a receiver, the same way a
Wi-Fi access point or a congested router sits between two hosts. Every packet
that passes through it, in either direction, can be:

  * dropped    - random (Bernoulli) loss, or bursty loss (Gilbert-Elliott model)
  * delayed    - a fixed propagation delay plus random jitter (in order,
                 like a real Wi-Fi link, packets are never reordered)
  * rate-limited - optional bottleneck link speed with a FIFO queue

Because the relay works on real UDP datagrams over real sockets, the
transports in transports.py experience genuine loss, delay and reordering,
not just numbers in a formula. We built this instead of using Linux `tc netem`
so the experiment runs on any OS (Windows, macOS, Linux) without root.
"""

import heapq
import random
import socket
import threading
import time


class GilbertElliott:
    """Two-state Markov loss model used for bursty wireless loss.

    GOOD state: packets pass.  BAD state: packets are dropped.
    p = P(GOOD -> BAD), r = P(BAD -> GOOD).
    Average loss = p / (p + r), mean burst length = 1 / r packets.
    """

    def __init__(self, avg_loss, mean_burst, rng):
        self.r = 1.0 / mean_burst
        self.p = avg_loss * self.r / (1.0 - avg_loss) if avg_loss < 1 else 1.0
        self.bad = False
        self.rng = rng

    def drop(self):
        if self.bad:
            if self.rng.random() < self.r:
                self.bad = False
        else:
            if self.rng.random() < self.p:
                self.bad = True
        return self.bad


class ImpairedLink(threading.Thread):
    """UDP relay that applies loss/delay/jitter to traffic in both directions.

    The sender talks to (127.0.0.1, self.port). The first address that is not
    the receiver is remembered as the sender, so replies (ACKs) can be routed
    back. Both directions are impaired independently, as on a real link.
    """

    def __init__(self, receiver_addr, loss=0.0, delay_ms=0.0, jitter_ms=0.0,
                 burst_len=0.0, rate_kbps=0.0, seed=1):
        super().__init__(daemon=True)
        self.receiver_addr = receiver_addr
        self.sender_addr = None
        self.delay = delay_ms / 1000.0
        self.jitter = jitter_ms / 1000.0
        self.rate = rate_kbps * 1000 / 8.0 if rate_kbps else 0.0  # bytes/s
        self.rng = random.Random(seed)
        self.loss = loss
        # one loss model per direction
        if burst_len and burst_len > 1:
            self.models = {d: GilbertElliott(loss, burst_len, self.rng) for d in ("fwd", "rev")}
        else:
            self.models = None
        self.link_free_at = {"fwd": 0.0, "rev": 0.0}
        # A Wi-Fi link delivers frames in order, so jitter must not reorder
        # packets: each packet leaves no earlier than the one before it.
        self.last_out = {"fwd": 0.0, "rev": 0.0}

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]

        self.queue = []          # heap of (deliver_time, counter, data, addr)
        self.counter = 0
        self.cv = threading.Condition()
        self.running = True
        self.stats = {"fwd_in": 0, "fwd_drop": 0, "rev_in": 0, "rev_drop": 0}
        self.sched = threading.Thread(target=self._scheduler, daemon=True)

    # ------------------------------------------------------------------ #
    def _should_drop(self, direction):
        if self.models:
            return self.models[direction].drop()
        return self.rng.random() < self.loss

    def _delay_for(self, direction, size, now):
        d = self.delay
        if self.jitter:
            d += self.rng.gauss(0, self.jitter)
            d = max(0.0, d)
        if self.rate:
            # serialisation on a bottleneck link: packets queue behind each other
            start = max(now, self.link_free_at[direction])
            self.link_free_at[direction] = start + size / self.rate
            d += self.link_free_at[direction] - now
        return d

    def run(self):
        self.sched.start()
        self.sock.settimeout(0.2)
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            now = time.monotonic()
            if addr == self.receiver_addr:
                direction, dst = "rev", self.sender_addr
                if dst is None:
                    continue
            else:
                self.sender_addr = addr
                direction, dst = "fwd", self.receiver_addr
            self.stats[direction + "_in"] += 1
            if self._should_drop(direction):
                self.stats[direction + "_drop"] += 1
                continue
            t = now + self._delay_for(direction, len(data), now)
            t = max(t, self.last_out[direction])      # FIFO: no reordering
            self.last_out[direction] = t
            with self.cv:
                self.counter += 1
                heapq.heappush(self.queue, (t, self.counter, data, dst))
                self.cv.notify()

    def _scheduler(self):
        while self.running:
            with self.cv:
                while self.running and not self.queue:
                    self.cv.wait(0.2)
                if not self.running:
                    return
                t, _, data, dst = self.queue[0]
                wait = t - time.monotonic()
                if wait > 0:
                    self.cv.wait(min(wait, 0.05))
                    continue
                heapq.heappop(self.queue)
            try:
                self.sock.sendto(data, dst)
            except OSError:
                pass

    def stop(self):
        self.running = False
        with self.cv:
            self.cv.notify_all()
        try:
            self.sock.close()
        except OSError:
            pass
