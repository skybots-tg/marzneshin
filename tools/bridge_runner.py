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
GEO = [("https://ipinfo.io/json", "ipinfo"),
       ("http://ip-api.com/json/?fields=status,countryCode,query", "ipapi")]


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
    if shape == "ipinfo":
        return d.get("country"), d.get("ip")
    if d.get("status") == "success":
        return d.get("countryCode"), d.get("query")
    return None, None


def run_job(job, socks_port, timeout):
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
        for url, shape in GEO:
            try:
                r = subprocess.run(
                    ["curl", "-s", "--socks5-hostname",
                     "127.0.0.1:%d" % socks_port, "--max-time", str(timeout),
                     url], capture_output=True, text=True, timeout=timeout + 5)
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
    if not ensure_xray():
        print(json.dumps({"error": "no xray binary on this vantage"}))
        return
    base = int(req.get("socks_base", 12100))
    results = {}

    def one(pair):
        idx, job = pair
        try:
            results[job["id"]] = run_job(job, base + (idx % workers), timeout)
        except Exception as exc:  # noqa: BLE001
            results[job["id"]] = {"verdict": "fail", "error": "runner_crash",
                                  "detail": str(exc)[:200]}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, enumerate(jobs)))
    print(json.dumps({"results": results}))


if __name__ == "__main__":
    main()
