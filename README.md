# AIRSPACE SCANNER

**Hidden Wi-Fi Camera & Drone Detector (Windows + Linux)**

Portable Windows app that scans 2.4 GHz and 5 / 5.8 GHz Wi-Fi airspace, classifies spy cameras and drones by MAC OUI + SSID + channel signatures, probes LAN camera ports, and helps you hunt targets with a live polar radar + acoustic Geiger counter.

Works with common USB Wi-Fi adapters (for example **Gembird WNP-UA1300-02 / Realtek RTL8812BU**). Keep your built-in Wi-Fi for internet; dedicate the USB adapter to scanning when available.

Repository: [github.com/mrproductionexpert-dot/AIRSPACE-SCANNER](https://github.com/mrproductionexpert-dot/AIRSPACE-SCANNER)

## What you need (Windows portable)

1. **Windows 10/11, 64-bit**
2. This repository (includes a **portable Python 3.12** under `runtime/python` — no system Python install required)
3. Optional: a USB Wi-Fi adapter for dedicated airspace sweeps
4. **Windows Location services ON** for *live* Wi-Fi scans (Microsoft requirement):
   - Open `ms-settings:privacy-location`
   - Enable **Location services**
   - Allow apps / desktop apps to access location

**Simulation Mode** works with zero hardware and does **not** need Location.

## Quick start (fully portable)

```bat
git clone https://github.com/mrproductionexpert-dot/AIRSPACE-SCANNER.git
cd AIRSPACE-SCANNER
run.bat
```

Or copy the whole folder (including `runtime\`) to a USB flash drive, plug it into any **64-bit Windows** PC, and double-click `run.bat`.

`run.bat` calls `run.ps1`, which uses `runtime\python\python.exe` (bundled), checks dependencies, and starts the server at **http://127.0.0.1:8765**.

## Run on Linux

Linux support is available via `nmcli` (NetworkManager).

Requirements:
- Python 3.10+
- `python3-venv` package
- NetworkManager / `nmcli` (`network-manager` package)

Ubuntu / Mint:

```bash
sudo apt update
sudo apt install -y python3 python3-venv network-manager
```

Start:

```bash
git clone https://github.com/mrproductionexpert-dot/AIRSPACE-SCANNER.git
cd AIRSPACE-SCANNER
chmod +x run.sh
./run.sh
```

Open **http://127.0.0.1:8765**

1. Select your USB Wi-Fi adapter in the dropdown (Realtek / WNP-UA1300-style adapters are auto-preferred when detected).
2. Or enable **Simulation** to demo drones / V380 / ESP-CAM / Hikvision-style blips immediately.
3. Click **Start Scan**.
4. Click a threat on the radar or device list to **lock** it — walk with the USB adapter; Geiger clicks speed up as RSSI rises.

## Detection engines

| Engine | How |
| --- | --- |
| Wi-Fi BSS scan | Windows: `wlanapi.dll` (`WlanScan` / `WlanGetNetworkBssList`) with `netsh` fallback. Linux: `nmcli` (NetworkManager) scan backend. |
| Signature classifier | OUI DB (DJI, Hikvision, Dahua, Espressif, V380/Xiongmai, Ring, Wyze, Reolink, …) + SSID regexes + 5.8 GHz video channels |
| LAN probe | ARP cache + RTSP/camera ports (`554`, `8554`, `8000`, `8080`, `1935`, `37777`, …) + NIC traffic burst rates |

## Project layout

```
runtime/python/     Portable CPython 3.12 (Windows x64) + app dependencies
app/                Scanner backend
static/             Radar UI, Geiger audio, waterfall
scripts/            Smoke test + portable Python rebuild script
run.bat             One-click launcher (uses bundled Python)
run.sh              Linux launcher (venv + deps install)
requirements.txt    Python dependencies
```

## Notes & limits (honest)

- Bundled runtime is **Windows amd64 only**. It will not run on 32-bit Windows or macOS/Linux.
- Windows and Linux default scans show **beaconing APs / soft-APs** (SSID, BSSID, RSSI, channel). They do **not** capture raw encrypted data-frame bursts like monitor-mode tools.
- Use only on networks and premises you own or are authorized to audit.
- Do not commit scan captures or logs — they are gitignored and may contain nearby network identifiers from *your* environment.

## License

MIT — for defensive / personal security research.
