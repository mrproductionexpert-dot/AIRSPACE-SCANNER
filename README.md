# AIRSPACE SCANNER

**Hidden Wi-Fi Camera & Drone Detector (Windows Native)**

Portable Windows app that scans 2.4 GHz and 5 / 5.8 GHz Wi-Fi airspace, classifies spy cameras and drones by MAC OUI + SSID + channel signatures, probes LAN camera ports, and helps you hunt targets with a live polar radar + acoustic Geiger counter.

Works with common USB Wi-Fi adapters (for example **Gembird WNP-UA1300-02 / Realtek RTL8812BU**). Keep your built-in Wi-Fi for internet; dedicate the USB adapter to scanning when available.

Repository: [github.com/mrproductionexpert-dot/AIRSPACE-SCANNER](https://github.com/mrproductionexpert-dot/AIRSPACE-SCANNER)

## What you need

1. Windows 10/11 PC
2. Python 3.10+ on PATH ([python.org](https://www.python.org/downloads/) — enable **Add python.exe to PATH**)
3. Optional: a USB Wi-Fi adapter for dedicated airspace sweeps
4. **Windows Location services ON** for *live* Wi-Fi scans (Microsoft requirement):
   - Open `ms-settings:privacy-location`
   - Enable **Location services**
   - Allow apps / desktop apps to access location

**Simulation Mode** works with zero hardware and does **not** need Location.

## Quick start (portable)

```bat
git clone https://github.com/mrproductionexpert-dot/AIRSPACE-SCANNER.git
cd AIRSPACE-SCANNER
run.bat
```

Or copy this folder to a USB flash drive, plug it into any Windows PC with Python installed, and double-click `run.bat`.

`run.bat` creates a local `.venv`, installs dependencies, starts the server, and opens the UI.

Manual:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m app.main
```

Open **http://127.0.0.1:8765**

1. Select your USB Wi-Fi adapter in the dropdown (Realtek / WNP-UA1300-style adapters are auto-preferred when detected).
2. Or enable **Simulation** to demo drones / V380 / ESP-CAM / Hikvision-style blips immediately.
3. Click **Start Scan**.
4. Click a threat on the radar or device list to **lock** it — walk with the USB adapter; Geiger clicks speed up as RSSI rises.

## Detection engines

| Engine | How |
| --- | --- |
| Win32 WLAN BSS scan | `wlanapi.dll` via ctypes (`WlanScan` / `WlanGetNetworkBssList`), with `netsh` fallback |
| Signature classifier | OUI DB (DJI, Hikvision, Dahua, Espressif, V380/Xiongmai, Ring, Wyze, Reolink, …) + SSID regexes + 5.8 GHz video channels |
| LAN probe | ARP cache + RTSP/camera ports (`554`, `8554`, `8000`, `8080`, `1935`, `37777`, …) + NIC traffic burst rates |

## Project layout

```
app/
  main.py           FastAPI + WebSocket telemetry
  wlan_win32.py     Windows Native Wi-Fi scanner
  signatures.py     Camera / drone intelligence DB
  network_probe.py  ARP / ports / traffic bursts
  classifier.py     Scoring, RSSI smoother, simulation
static/             Radar UI, Geiger audio, waterfall
scripts/            Optional smoke test against a running server
run.bat             One-click launcher
requirements.txt    Python dependencies
```

## Notes & limits (honest)

- Windows managed-mode BSS scans show **beaconing APs / soft-APs** (SSID, BSSID, RSSI, channel). They do **not** capture raw encrypted data-frame bursts from stations the way Linux monitor mode does.
- A dedicated USB adapter + Simulation Mode still give a practical anti-spy workflow: find camera setup APs, drone soft-APs, strong 5.8 GHz video channels, and LAN RTSP endpoints, then Geiger-walk to the hottest RSSI.
- Use only on networks and premises you own or are authorized to audit.
- Do not commit local `.venv`, scan captures, or logs — they are gitignored and may contain nearby network identifiers from *your* environment.

## License

MIT — for defensive / personal security research.
