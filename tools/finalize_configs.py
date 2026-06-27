"""Substitute __KEY_n__ placeholders in <ip>.new.json with the real reality
private keys generated on each node (<ip>.keys.txt). Writes <ip>.final.json
and asserts no placeholder remains."""
import json
import os

BASE = os.path.join(os.path.dirname(__file__), "..", ".tmp_uni_configs")
IPS = ["89.191.225.218", "84.252.101.98", "5.35.125.174"]


def read_text(path):
    for enc in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            with open(path, encoding=enc) as f:
                t = f.read()
            return t
        except (UnicodeError, UnicodeDecodeError):
            continue
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def main():
    for ip in IPS:
        cfg_txt = read_text(os.path.join(BASE, f"{ip}.new.json"))
        keys = [ln.strip() for ln in read_text(
            os.path.join(BASE, f"{ip}.keys.txt")).splitlines() if ln.strip()]
        # sanity: keys look like base64url 43 chars
        keys = [k for k in keys if len(k) >= 40 and "PrivateKey" not in k]
        n_needed = cfg_txt.count("__KEY_")
        # count distinct placeholders
        idxs = sorted({int(s.split("__KEY_")[1].split("__")[0])
                       for s in [cfg_txt[m:m+20] for m in
                                 range(len(cfg_txt)) if cfg_txt.startswith("__KEY_", m)]})
        if len(keys) < len(idxs):
            raise SystemExit(f"{ip}: need {len(idxs)} keys, have {len(keys)}")
        for i in idxs:
            cfg_txt = cfg_txt.replace(f"__KEY_{i}__", keys[i])
        if "__KEY_" in cfg_txt or "__PLACEHOLDER__" in cfg_txt:
            raise SystemExit(f"{ip}: placeholder still present after substitution")
        # validate JSON round-trips
        obj = json.loads(cfg_txt)
        out = os.path.join(BASE, f"{ip}.final.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        print(f"{ip}: OK  placeholders_filled={len(idxs)}  "
              f"inbounds={len(obj['inbounds'])} outbounds={len(obj['outbounds'])} "
              f"rules={len(obj['routing']['rules'])}")


if __name__ == "__main__":
    main()
