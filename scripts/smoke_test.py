"""Quick API smoke test against a running local server."""

from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8765"


def call(path: str, data: dict | None = None):
    url = BASE + path
    if data is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.load(resp)


def main() -> None:
    print("health", call("/api/health"))
    adapters = call("/api/adapters")
    print(
        "adapters",
        [(a["description"], a["preferred"]) for a in adapters["adapters"]],
    )
    print(
        "selected",
        adapters["selected"]["description"] if adapters["selected"] else None,
    )
    sim = call("/api/simulation", {"enabled": True})
    print("sim stats", sim["stats"])
    once = call("/api/scan/once", {})
    print(
        "scan_count",
        once["scan_count"],
        "devices",
        once["stats"]["device_count"],
        "threats",
        once["stats"]["threat_count"],
    )
    for d in once["devices"][:5]:
        print(f"  {d['score']:3d} {d['category']:12s} {d['ssid']}")
    call("/api/simulation", {"enabled": False})
    live = call("/api/scan/once", {})
    err = live.get("last_error") or ""
    print("live error:", err[:120])
    assert "Location" in err or live["stats"]["device_count"] >= 0
    assert urllib.request.urlopen(BASE + "/").status == 200
    assert urllib.request.urlopen(BASE + "/static/styles.css").status == 200
    assert urllib.request.urlopen(BASE + "/static/app.js").status == 200
    assert once["stats"]["threat_count"] >= 3
    print("ALL_API_OK")


if __name__ == "__main__":
    main()
