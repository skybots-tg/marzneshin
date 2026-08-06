#!/usr/bin/env python3
"""Probe worker that runs ON A VANTAGE NODE, not on the panel.

Copied to a node and fed a job list on stdin; prints one JSON result object on
stdout. It is deliberately standalone (stdlib only, no imports from the tools
package) because it executes on VPN nodes that only have the marznode
container and a bare python3.

Why it exists: RU hosting providers routinely drop foreign traffic before the
TLS handshake, so probing a RU entry node from the panel in Norway reports
healthy bridges as dead. Running the same probe from another RU node reproduces
what a real subscriber sees.

stdin:  {"jobs": [{"id": "...", "client": <xray client config>}],
         "workers": 6, "timeout": 12}
stdout: {"results": {"<id>": {"verdict": ..., "country": ..., ...}}}
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

XRAY = "/tmp/xray_bridge_probe"

# Several geo lookups, rotated per job. ip-api.com allows only ~45 requests a
# minute per source IP, and a sweep of 100+ hosts blows straight through that;
# a rate-limited lookup is indistinguishable from a dead bridge, so spreading
# the load across providers is what keeps the verdicts honest.
GEO = [
    ("https://ipinfo.io/json", "ipinfo"),
    ("https://api.country.is/", "countryis"),
    ("http://ip-api.com/json/?fields=status,countryCode,query", "ipapi"),
]


def ensure_xray():
    if os.path.exists(XRAY) and os.access(XRAY, os.X_OK):
        return True
    cn = subprocess.run(
        "docker ps --format '{{.Names}}' | grep -i marz | grep -vi db | head -1",
        shell=True, capture_output=True, text=True).stdout.strip()
    if cn:
        subprocess.run(f"docker cp {cn}:/usr/local/bin/xray {XRAY}",
                       shell=True, capture_output=True)
    if not os.path.exists(XRAY):
        for cand in ("/usr/local/bin/xray", "/usr/bin/xray"):
            if os.path.exists(cand):
                subprocess.run(["cp", cand, XRAY], capture_output=True)
                break
    if os.path.exists(XRAY):
        os.chmod(XRAY, 0o755)
        return True
    return False


def parse_geo(raw, shape):
    try:
        d = json.loads(raw)
    except Exception:
        return None, None
    if shape in ("ipinfo", "countryis"):
        return d.get("country"), d.get("ip")
    if d.get("status") == "success":
        return d.get("countryCode"), d.get("query")
    return None, None


def run_job(job, socks_port, timeout, geo_offset=0, deadline=None):
    cfg = job["client"]
    cfg["inbounds"][0]["port"] = socks_port
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(cfg, f)
    f.close()
    log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
    p = subprocess.Popen([XRAY, "run", "-c", f.name],
                         stdout=log, stderr=subprocess.STDOUT)
    time.sleep(1.6)
    country = ip = None
    t0 = time.time()
    try:
        if p.poll() is not None:
            log.seek(0)
            return {"verdict": "fail", "error": "xray_client_exited",
                    "detail": log.read()[-300:]}
        rotated = GEO[geo_offset % len(GEO):] + GEO[:geo_offset % len(GEO)]
        for url, shape in rotated:
            budget = timeout
            if deadline:
                budget = min(timeout, int(deadline - time.time()))
                if budget < 4:
                    break
            try:
                r = subprocess.run(
                    ["curl", "-s", "--socks5-hostname",
                     "127.0.0.1:%d" % socks_port, "--max-time", str(budget),
                     url], capture_output=True, text=True, timeout=budget + 5)
            except Exception:
                continue
            country, ip = parse_geo(r.stdout.strip(), shape)
            if country:
                break
    finally:
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(timeout=4)
        except Exception:
            p.kill()
        log.seek(0)
        tail = log.read()[-300:]
        log.close()
        for path in (f.name, log.name):
            try:
                os.unlink(path)
            except OSError:
                pass
    elapsed = round(time.time() - t0, 1)
    if not country:
        return {"verdict": "fail", "error": "no_egress", "detail": tail,
                "elapsed": elapsed}
    return {"verdict": "pass", "country": country, "egress_ip": ip,
            "elapsed": elapsed}


def main():
    req = json.load(sys.stdin)
    jobs = req["jobs"]
    workers = int(req.get("workers", 6))
    timeout = int(req.get("timeout", 12))
    attempts = int(req.get("attempts", 2))
    if not ensure_xray():
        print(json.dumps({"error": "no xray binary on this vantage"}))
        return
    base = int(req.get("socks_base", 12100))
    # Hard wall clock. Without it a handful of stalled probes can outlive the
    # dispatcher's ssh timeout, and the whole vantage is then thrown away —
    # turning a slow node into "nothing is reachable from here".
    deadline = time.time() + float(req.get("deadline") or 3600)
    results = {}

    def one(pair):
        idx, job = pair
        # Every job gets its own listen port for the whole run. Reusing ports
        # across jobs lets a lingering xray from a finished probe answer the
        # next one's curl, which silently reports another server's country.
        if time.time() >= deadline:
            results.setdefault(job["id"], {"verdict": "skip",
                                           "error": "deadline"})
            return
        try:
            results[job["id"]] = run_job(job, base + idx, timeout,
                                         geo_offset=idx, deadline=deadline)
        except Exception as exc:  # noqa: BLE001
            results[job["id"]] = {"verdict": "fail", "error": "runner_crash",
                                  "detail": str(exc)[:200]}

    indexed = list(enumerate(jobs))
    for attempt in range(attempts):
        if not indexed or time.time() >= deadline:
            break
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, indexed))
        # Retry only the failures, once the first sweep has drained: a lot of
        # them are geo-lookup rate limits rather than a dead route.
        indexed = [(i, j) for i, j in indexed
                   if results.get(j["id"], {}).get("verdict") != "pass"]
        if indexed and attempt + 1 < attempts:
            time.sleep(5)
    print(json.dumps({"results": results}))


if __name__ == "__main__":
    main()
