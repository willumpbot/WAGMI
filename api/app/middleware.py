import time
from fastapi import Request
from prometheus_client import Counter, Histogram

# Keep a minimal in-memory snapshot (for backwards compat) while also
# emitting Prometheus metrics.
from collections import defaultdict, deque
import threading


class Metrics:
    def __init__(self, window: int = 500):
        self.lock = threading.Lock()
        self.req = defaultdict(int)
        self.err = defaultdict(int)
        self.lat = defaultdict(lambda: deque(maxlen=window))

    def record(self, key: str, ok: bool, ms: float):
        with self.lock:
            self.req[key] += 1
            if not ok:
                self.err[key] += 1
            self.lat[key].append(ms)

    def snapshot(self):
        with self.lock:
            def quantiles(vals):
                if not vals:
                    return {"p50": 0.0, "p95": 0.0}
                s = sorted(vals)
                def q(p):
                    i = int(max(0, min(len(s) - 1, round((p/100) * (len(s)-1)))))
                    return float(s[i])
                return {"p50": q(50), "p95": q(95)}

            return {
                "requests": dict(self.req),
                "errors": dict(self.err),
                "latency_ms": {k: quantiles(list(v)) for k, v in self.lat.items()},
            }


metrics = Metrics()

# Prometheus metrics: labeled by path and status
REQUEST_COUNTER = Counter(
    "nunuirl_requests_total",
    "Total HTTP requests",
    ["path", "status"],
)

ERROR_COUNTER = Counter(
    "nunuirl_errors_total",
    "Total HTTP errors",
    ["path", "status"],
)

LATENCY_HIST = Histogram(
    "nunuirl_request_latency_seconds",
    "Request latency in seconds",
    ["path", "status"],
    buckets=(0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5),
)


async def metrics_middleware(request: Request, call_next):
    route = request.url.path
    t0 = time.perf_counter()
    status = "500"
    try:
        response = await call_next(request)
        status = str(response.status_code)
        return response
    except Exception:
        status = "500"
        raise
    finally:
        ms = (time.perf_counter() - t0)
        ok = status.startswith("2") or status.startswith("3")
        # record in-memory snapshot (ms -> ms)
        metrics.record(route, ok, ms * 1000.0)
        # Prometheus (histogram expects seconds)
        REQUEST_COUNTER.labels(path=route, status=status).inc()
        if not ok:
            ERROR_COUNTER.labels(path=route, status=status).inc()
        LATENCY_HIST.labels(path=route, status=status).observe(ms)
