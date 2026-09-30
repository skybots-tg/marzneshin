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


# What "the tunnel works" has to mean. A single geo lookup answering, out of up
# to six tries, used to be the whole bar -- and a leg whose DPI kills four
# connections in five clears it nearly every time. On 2026-09-30 every AdminVPS
# bridge passed the audit while not one 5 MB download through them even started,
# and the automation kept putting them back into subscriptions. So once the
# lookup answers, the same tunnel has to carry these too, a real download among
# them; one failure is enough, since a working leg drops none of them.
#
# Google only, on purpose. RU Direct hosts exit from RU datacentres, and those
# lose foreign networks piecemeal: on 2026-09-30 DataCheap RU-1 reached Google
# but neither Cloudflare nor OVH, so a Cloudflare download here would have hidden
# RU Direct hosts that serve Russian sites perfectly well. Every node in the
# fleet, the restricted ones included, fetched all three of these.
SUSTAIN = [
    ("https://www.google.com/generate_204", 0),
    ("https://connectivitycheck.gstatic.com/generate_204", 0),
    ("https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb",
     262144),
]
SUSTAIN_TIMEOUT = 8
SUSTAIN_WORST = len(SUSTAIN) * (SUSTAIN_TIMEOUT + 1)


def sustained(socks_port, run=subprocess.run):
    """How many of SUSTAIN went through, stopping at the first that did not."""
    done = 0
    for url, size in SUSTAIN:
        cmd = ["curl", "-s", "-o", "/dev/null", "--socks5-hostname",
               "127.0.0.1:%d" % socks_port, "--max-time", str(SUSTAIN_TIMEOUT),
               "-w", "%{http_code} %{size_download}"]
        if size:
            cmd += ["-r", "0-%d" % (size - 1)]   # a slice, not the whole file
        try:
            r = run(cmd + [url], capture_output=True, text=True,
                    timeout=SUSTAIN_TIMEOUT + 5)
            code, got = (r.stdout.split() + ["000", "0"])[:2]
        except Exception:
            break
        if not code.startswith(("2", "3")) or int(float(got)) < size:
            break
        done += 1
    return done


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


def run_job(job, socks_port, timeout, geo_offset=0, deadline=None,
            geo_tries=None):
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
        # A failing job pays for every endpoint in turn, which is what makes a
        # full sweep slow. The watchdog trades that thoroughness for speed: one
        # endpoint is enough to answer "did anything come back", and a rate
        # limit mistaken for a failure costs a streak, not a hidden host.
        if geo_tries:
            rotated = rotated[:geo_tries]
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
        carried = sustained(socks_port) if country else 0
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
    if carried < len(SUSTAIN):
        # Reached the far end once, then lost the next connections: the leg is
        # throttled, and a subscriber on it gets a page that half-loads.
        return {"verdict": "fail", "error": "throttled", "country": country,
                "egress_ip": ip, "sustained": "%d/%d" % (carried, len(SUSTAIN)),
                "detail": tail, "elapsed": elapsed}
    return {"verdict": "pass", "country": country, "egress_ip": ip,
            "elapsed": elapsed}


def main():
    # The clock starts here, not after the setup below: the dispatcher's ssh
    # timeout is derived from the same budget, so anything spent before the
    # wall clock exists is time the dispatcher has already counted and this
    # process has not. Copying the xray binary out of the container is usually
    # instant and occasionally is not, which is exactly how a run overshoots.
    started = time.time()
    req = json.load(sys.stdin)
    jobs = req["jobs"]
    workers = int(req.get("workers", 6))
    timeout = int(req.get("timeout", 12))
    attempts = int(req.get("attempts", 2))
    geo_tries = int(req.get("geo_tries") or 0) or None
    if not ensure_xray():
        print(json.dumps({"error": "no xray binary on this vantage"}))
        return
    base = int(req.get("socks_base", 12100))
    # Hard wall clock. Without it a handful of stalled probes can outlive the
    # dispatcher's ssh timeout, and the whole vantage is then thrown away —
    # turning a slow node into "nothing is reachable from here".
    deadline = started + float(req.get("deadline") or 3600)
    # The longest a single job can take: xray warm-up, every geo lookup it is
    # allowed, and the teardown. Starting a job with less than this left is how
    # the run overshoots the deadline it was given.
    worst_job = 2 + (geo_tries or len(GEO)) * (timeout + 5) + SUSTAIN_WORST + 5
    results = {}

    def one(pair):
        idx, job = pair
        # Every job gets its own listen port for the whole run. Reusing ports
        # across jobs lets a lingering xray from a finished probe answer the
        # next one's curl, which silently reports another server's country.
        if time.time() + worst_job > deadline:
            results.setdefault(job["id"], {"verdict": "skip",
                                           "error": "deadline"})
            return
        try:
            results[job["id"]] = run_job(job, base + idx, timeout,
                                         geo_offset=idx, deadline=deadline,
                                         geo_tries=geo_tries)
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
