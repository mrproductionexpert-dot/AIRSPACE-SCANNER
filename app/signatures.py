"""Camera, drone, and IoT RF / OUI / SSID signature intelligence database."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Normalized OUI -> (vendor, category, base_score)
# Categories: DRONE | HIDDEN_CAM | IP_CAMERA | IOT_CAMERA | ROUTER | UNKNOWN
OUI_DB: dict[str, tuple[str, str, int]] = {
    # Drones
    "60:60:1F": ("DJI", "DRONE", 95),
    "34:D2:62": ("DJI", "DRONE", 95),
    "48:1C:B9": ("DJI", "DRONE", 95),
    "A0:14:3D": ("Parrot", "DRONE", 90),
    "90:03:B7": ("Parrot", "DRONE", 90),
    "00:12:1C": ("Parrot", "DRONE", 90),
    "00:26:7E": ("Parrot", "DRONE", 90),
    "B0:B4:48": ("Autel Robotics", "DRONE", 90),
    "E0:B9:4D": ("Skydio", "DRONE", 88),
    # IP / NVR camera vendors
    "44:19:B6": ("Hikvision", "IP_CAMERA", 85),
    "C0:56:E3": ("Hikvision", "IP_CAMERA", 85),
    "28:57:BE": ("Hikvision", "IP_CAMERA", 85),
    "BC:AD:28": ("Hikvision", "IP_CAMERA", 85),
    "4C:BD:8F": ("Hangzhou Hikvision", "IP_CAMERA", 85),
    "3C:EF:8C": ("Zhejiang Dahua", "IP_CAMERA", 85),
    "A0:BD:1D": ("Zhejiang Dahua", "IP_CAMERA", 85),
    "08:ED:ED": ("Zhejiang Dahua", "IP_CAMERA", 85),
    "6C:1C:71": ("Zhejiang Dahua", "IP_CAMERA", 85),
    "54:C4:15": ("Hangzhou Hikvision", "IP_CAMERA", 85),
    "2C:AB:00": ("Huawei Camera", "IP_CAMERA", 70),
    "00:12:12": ("Vivotek", "IP_CAMERA", 80),
    "00:02:D1": ("Vivotek", "IP_CAMERA", 80),
    "00:40:8C": ("Axis Communications", "IP_CAMERA", 82),
    "AC:CC:8E": ("Axis Communications", "IP_CAMERA", 82),
    "B8:A4:4F": ("Axis Communications", "IP_CAMERA", 82),
    "00:1A:07": ("Arecont Vision", "IP_CAMERA", 78),
    "00:0F:7C": ("Reolink / related", "IP_CAMERA", 80),
    "EC:71:DB": ("Reolink", "IP_CAMERA", 82),
    "94:E3:6D": ("Wyze Labs", "IP_CAMERA", 78),
    "2C:AA:8E": ("Wyze Labs", "IP_CAMERA", 78),
    "7C:78:B2": ("Wyze Labs", "IP_CAMERA", 78),
    "B0:C5:54": ("Ring / Amazon", "IP_CAMERA", 75),
    "24:4C:E3": ("Amazon Ring", "IP_CAMERA", 75),
    "68:54:FD": ("Amazon Devices", "IP_CAMERA", 70),
    "F0:27:2D": ("Amazon Technologies", "IP_CAMERA", 68),
    "00:17:88": ("Philips Hue / Signify", "IOT_CAMERA", 40),
    # Espressif / cheap spy-cam modules
    "24:0A:C4": ("Espressif", "IOT_CAMERA", 72),
    "24:6F:28": ("Espressif", "IOT_CAMERA", 72),
    "30:AE:A4": ("Espressif", "IOT_CAMERA", 72),
    "3C:71:BF": ("Espressif", "IOT_CAMERA", 72),
    "48:3F:DA": ("Espressif", "IOT_CAMERA", 72),
    "4C:11:AE": ("Espressif", "IOT_CAMERA", 72),
    "5C:CF:7F": ("Espressif", "IOT_CAMERA", 72),
    "60:01:94": ("Espressif", "IOT_CAMERA", 72),
    "68:C6:3A": ("Espressif", "IOT_CAMERA", 72),
    "84:0D:8E": ("Espressif", "IOT_CAMERA", 72),
    "84:CC:A8": ("Espressif", "IOT_CAMERA", 72),
    "8C:AA:B5": ("Espressif", "IOT_CAMERA", 72),
    "90:97:D5": ("Espressif", "IOT_CAMERA", 72),
    "A0:20:A6": ("Espressif", "IOT_CAMERA", 72),
    "A4:CF:12": ("Espressif", "IOT_CAMERA", 72),
    "AC:67:B2": ("Espressif", "IOT_CAMERA", 72),
    "B4:E6:2D": ("Espressif", "IOT_CAMERA", 72),
    "BC:DD:C2": ("Espressif", "IOT_CAMERA", 72),
    "C4:4F:33": ("Espressif", "IOT_CAMERA", 72),
    "C8:2B:96": ("Espressif", "IOT_CAMERA", 72),
    "CC:50:E3": ("Espressif", "IOT_CAMERA", 72),
    "D8:A0:1D": ("Espressif", "IOT_CAMERA", 72),
    "DC:4F:22": ("Espressif", "IOT_CAMERA", 72),
    "E0:98:06": ("Espressif", "IOT_CAMERA", 72),
    "EC:FA:BC": ("Espressif", "IOT_CAMERA", 72),
    "F4:CF:A2": ("Espressif", "IOT_CAMERA", 72),
    "FC:F5:C4": ("Espressif", "IOT_CAMERA", 72),
    # Realtek / Beken IoT Wi-Fi modules often used in cheap cameras
    "00:E0:4C": ("Realtek", "IOT_CAMERA", 55),
    "52:54:00": ("QEMU/Virtual", "UNKNOWN", 5),
    "00:0C:43": ("Ralink / MediaTek", "IOT_CAMERA", 50),
    "C8:3A:35": ("Tenda / IoT", "IOT_CAMERA", 55),
    "D8:F1:5B": ("TP-Link IoT", "IOT_CAMERA", 50),
    "50:C7:BF": ("TP-Link", "ROUTER", 20),
    "F4:F2:6D": ("TP-Link", "ROUTER", 20),
    "14:CC:20": ("TP-Link", "ROUTER", 20),
    "A0:F3:C1": ("TP-Link", "ROUTER", 20),
    "B0:BE:76": ("TP-Link", "ROUTER", 20),
    "C0:25:E9": ("TP-Link", "ROUTER", 20),
    "18:A6:F7": ("TP-Link", "ROUTER", 20),
    "98:DA:C4": ("TP-Link", "ROUTER", 20),
    "60:32:B1": ("TP-Link / Tether", "ROUTER", 25),
    "E4:F0:42": ("Google Nest", "IP_CAMERA", 65),
    "18:B4:30": ("Nest Labs", "IP_CAMERA", 70),
    "64:16:66": ("Nest Labs", "IP_CAMERA", 70),
    "F4:F5:D8": ("Google", "IP_CAMERA", 55),
    "54:60:09": ("Google", "IP_CAMERA", 55),
    # Xiaomi / Yi / Imou
    "28:6C:07": ("Xiaomi", "IP_CAMERA", 65),
    "34:CE:00": ("Xiaomi", "IP_CAMERA", 65),
    "64:B4:73": ("Xiaomi", "IP_CAMERA", 65),
    "78:11:DC": ("Xiaomi", "IP_CAMERA", 65),
    "F0:B4:29": ("Xiaomi", "IP_CAMERA", 65),
    "50:8F:4C": ("Xiaomi", "IP_CAMERA", 65),
    "04:CF:8C": ("Xiaomi", "IP_CAMERA", 65),
    "7C:49:EB": ("Xiongmai / XM", "HIDDEN_CAM", 88),
    "00:12:16": ("Xiongmai Technology", "HIDDEN_CAM", 88),
    # Ubiquiti / Amcrest / Foscam
    "FC:EC:DA": ("Ubiquiti", "IP_CAMERA", 60),
    "24:A4:3C": ("Ubiquiti", "IP_CAMERA", 60),
    "00:0D:C5": ("Digi International / DigiCam", "IP_CAMERA", 60),
    "00:0F:E2": ("Hangzhou H3C / cameras", "IP_CAMERA", 60),
    "C4:2F:90": ("Hangzhou Hikvision", "IP_CAMERA", 85),
    "E0:50:8B": ("Hangzhou Hikvision", "IP_CAMERA", 85),
}

# SSID patterns commonly used by spy cams / drone soft-APs / setup modes
SSID_PATTERNS: list[tuple[re.Pattern[str], str, str, int]] = [
    (re.compile(r"^DJI[-_]?", re.I), "DJI soft-AP", "DRONE", 96),
    (re.compile(r"^MAVIC", re.I), "DJI Mavic", "DRONE", 96),
    (re.compile(r"^PHANTOM", re.I), "DJI Phantom", "DRONE", 96),
    (re.compile(r"^MINI[-_]?\d", re.I), "DJI Mini", "DRONE", 90),
    (re.compile(r"^AIR[-_]?\d", re.I), "DJI Air", "DRONE", 90),
    (re.compile(r"^AUTEL", re.I), "Autel soft-AP", "DRONE", 92),
    (re.compile(r"^SKYDIO", re.I), "Skydio soft-AP", "DRONE", 92),
    (re.compile(r"^ANAFI", re.I), "Parrot Anafi", "DRONE", 90),
    (re.compile(r"^BEBOP", re.I), "Parrot Bebop", "DRONE", 90),
    (re.compile(r"^IPC[-_]?", re.I), "IP Camera soft-AP", "HIDDEN_CAM", 88),
    (re.compile(r"^IPCAM", re.I), "IP Camera", "HIDDEN_CAM", 88),
    (re.compile(r"^CAM[-_]?\d", re.I), "Camera soft-AP", "HIDDEN_CAM", 82),
    (re.compile(r"^CAMERA[-_]?", re.I), "Camera soft-AP", "HIDDEN_CAM", 80),
    (re.compile(r"^V380", re.I), "V380 spy camera", "HIDDEN_CAM", 94),
    (re.compile(r"^V380PRO", re.I), "V380 Pro", "HIDDEN_CAM", 94),
    (re.compile(r"^LOOKCAM", re.I), "LookCam", "HIDDEN_CAM", 92),
    (re.compile(r"^MV\d{4}", re.I), "MicroVision / spy cam", "HIDDEN_CAM", 90),
    (re.compile(r"^HIPCAM", re.I), "Hipcam", "HIDDEN_CAM", 90),
    (re.compile(r"^HOCAM", re.I), "Hocam", "HIDDEN_CAM", 88),
    (re.compile(r"^GWSEC", re.I), "Generic WiFi camera", "HIDDEN_CAM", 85),
    (re.compile(r"^ESP[-_]?(CAM|32)", re.I), "ESP32-CAM", "IOT_CAMERA", 85),
    (re.compile(r"^AI[-_]?THINKER", re.I), "AI-Thinker ESP-CAM", "IOT_CAMERA", 85),
    (re.compile(r"^WYZE", re.I), "Wyze setup AP", "IP_CAMERA", 75),
    (re.compile(r"^REOLINK", re.I), "Reolink setup AP", "IP_CAMERA", 78),
    (re.compile(r"^RING[-_]?", re.I), "Ring setup AP", "IP_CAMERA", 75),
    (re.compile(r"^NEST[-_]?(CAM|DOORBELL)", re.I), "Nest Camera", "IP_CAMERA", 75),
    (re.compile(r"^FOSCAM", re.I), "Foscam", "IP_CAMERA", 80),
    (re.compile(r"^AMCREST", re.I), "Amcrest", "IP_CAMERA", 80),
    (re.compile(r"^TP[-_]?LINK[_-]?IP", re.I), "TP-Link IP Cam", "IP_CAMERA", 75),
    (re.compile(r"^TAPO[_-]?C", re.I), "TP-Link Tapo Cam", "IP_CAMERA", 78),
    (re.compile(r"^IMOU[-_]?", re.I), "Imou Camera", "IP_CAMERA", 78),
    (re.compile(r"^EZVIZ", re.I), "Ezviz Camera", "IP_CAMERA", 78),
    (re.compile(r"^HIKVISION", re.I), "Hikvision AP", "IP_CAMERA", 85),
    (re.compile(r"^DAHUA", re.I), "Dahua AP", "IP_CAMERA", 85),
    (re.compile(r"^XIAOFANG", re.I), "Xiaofang Cam", "IP_CAMERA", 80),
    (re.compile(r"^YI[-_]?CAMERA", re.I), "Yi Camera", "IP_CAMERA", 78),
    (re.compile(r"^CLOUDCAM", re.I), "CloudCam", "HIDDEN_CAM", 85),
    (re.compile(r"^SPY[-_]?CAM", re.I), "Spy Cam", "HIDDEN_CAM", 95),
    (re.compile(r"^HIDDEN[-_]?", re.I), "Suspicious SSID", "HIDDEN_CAM", 70),
    (re.compile(r"^DIRECT[-_]?[\da-f]{4}", re.I), "Wi-Fi Direct soft-AP", "IOT_CAMERA", 45),
]

# 5.8 GHz UNII-3 channels often used by FPV / drone video / outdoor cams
VIDEO_HEAVY_CHANNELS_5G = {149, 153, 157, 161, 165}

# Camera streaming ports
CAMERA_PORTS = (554, 8554, 8000, 8080, 8081, 8443, 1935, 37777, 34567, 9000, 10554)

CATEGORY_LABELS = {
    "DRONE": "Drone / UAV",
    "HIDDEN_CAM": "Hidden / Spy Camera AP",
    "IP_CAMERA": "IP / Smart Camera",
    "IOT_CAMERA": "IoT Camera Module",
    "IOT_SENSOR": "IoT Sensor",
    "STANDARD_AP": "Standard Access Point",
    "ROUTER": "Router / AP",
    "UNKNOWN": "Unknown Transmitter",
}


@dataclass
class SignatureHit:
    vendor: str
    category: str
    score: int
    reason: str


def normalize_oui(mac: str) -> str:
    clean = mac.upper().replace("-", ":").strip()
    parts = clean.split(":")
    if len(parts) >= 3:
        return ":".join(parts[:3])
    return clean[:8]


def lookup_oui(mac: str) -> Optional[SignatureHit]:
    oui = normalize_oui(mac)
    hit = OUI_DB.get(oui)
    if not hit:
        return None
    vendor, category, score = hit
    return SignatureHit(
        vendor=vendor,
        category=category,
        score=score,
        reason=f"OUI {oui} -> {vendor}",
    )


def lookup_ssid(ssid: str) -> Optional[SignatureHit]:
    if not ssid:
        return None
    for pattern, label, category, score in SSID_PATTERNS:
        if pattern.search(ssid):
            return SignatureHit(
                vendor=label,
                category=category,
                score=score,
                reason=f"SSID match '{ssid}' -> {label}",
            )
    return None


def channel_bonus(channel: int, band: str) -> tuple[int, str]:
    if band in ("5", "5.8") and channel in VIDEO_HEAVY_CHANNELS_5G:
        return 8, f"5.8 GHz video-heavy channel {channel}"
    if band == "5.8":
        return 5, f"5.8 GHz band channel {channel}"
    return 0, ""
