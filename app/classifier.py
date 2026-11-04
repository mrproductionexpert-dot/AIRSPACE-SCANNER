"""Threat scoring, RSSI smoothing, and distance estimation."""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .network_probe import LanHost
from .signatures import (
    CATEGORY_LABELS,
    SignatureHit,
    channel_bonus,
    lookup_oui,
    lookup_ssid,
)
from .wlan_win32 import BssEntry


def rssi_to_meters(rssi: int, tx_power_dbm: float = -40.0, n: float = 2.5) -> float:
    """Log-distance path-loss estimate. Rough indoor calibration."""
    if rssi >= 0:
        return 0.3
    # d = 10 ^ ((TxPower - RSSI) / (10 * n))
    try:
        meters = 10 ** ((tx_power_dbm - rssi) / (10.0 * n))
    except OverflowError:
        meters = 100.0
    return float(max(0.3, min(80.0, meters)))


class RollingRssi:
    """Simple 1D Kalman-like EMA smoother for RSSI."""

    def __init__(self, alpha: float = 0.35, history: int = 60) -> None:
        self.alpha = alpha
        self.value: Optional[float] = None
        self.history: deque[tuple[float, float]] = deque(maxlen=history)

    def update(self, rssi: float, ts: Optional[float] = None) -> float:
        ts = ts or time.time()
        if self.value is None:
            self.value = float(rssi)
        else:
            self.value = self.alpha * float(rssi) + (1.0 - self.alpha) * self.value
        self.history.append((ts, self.value))
        return self.value

    def variance(self) -> float:
        if len(self.history) < 3:
            return 0.0
        vals = [v for _, v in self.history]
        mean = sum(vals) / len(vals)
        return sum((v - mean) ** 2 for v in vals) / len(vals)


@dataclass
class ClassifiedDevice:
    bssid: str
    ssid: str
    rssi: int
    rssi_smooth: float
    distance_m: float
    channel: int
    band: str
    frequency_mhz: int
    phy_type: str
    category: str
    category_label: str
    vendor: str
    score: int
    reasons: list[str] = field(default_factory=list)
    angle_deg: float = 0.0  # synthetic radar angle from channel hash
    first_seen: float = 0.0
    last_seen: float = 0.0
    source: str = "wifi"
    lan_ip: Optional[str] = None
    open_ports: list[int] = field(default_factory=list)
    rssi_history: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeviceTracker:
    """Tracks devices across scans, smooths RSSI, merges LAN hits."""

    def __init__(self) -> None:
        self._rssi: dict[str, RollingRssi] = {}
        self._devices: dict[str, ClassifiedDevice] = {}
        self._first_seen: dict[str, float] = {}

    def reset(self) -> None:
        self._rssi.clear()
        self._devices.clear()
        self._first_seen.clear()

    def _angle_for(self, bssid: str, channel: int) -> float:
        # Deterministic polar placement: mix channel sector + MAC hash
        h = sum(ord(c) for c in bssid) % 360
        sector = (channel % 36) * (360 / 36)
        return (0.55 * sector + 0.45 * h) % 360.0

    def classify_bss(self, entry: BssEntry, now: Optional[float] = None) -> ClassifiedDevice:
        now = now or time.time()
        key = entry.bssid.upper()
        smoother = self._rssi.setdefault(key, RollingRssi())
        smooth = smoother.update(entry.rssi, now)
        if key not in self._first_seen:
            self._first_seen[key] = now

        reasons: list[str] = []
        score = 10
        vendor = "Unknown"
        category = "UNKNOWN"

        oui = lookup_oui(entry.bssid)
        ssid_hit = lookup_ssid(entry.ssid)

        def apply(hit: SignatureHit, weight: float = 1.0) -> None:
            nonlocal score, vendor, category
            score = max(score, int(hit.score * weight))
            if hit.category in ("DRONE", "HIDDEN_CAM") or category in ("UNKNOWN", "ROUTER", "STANDARD_AP"):
                category = hit.category
                vendor = hit.vendor
            elif hit.score >= score:
                category = hit.category
                vendor = hit.vendor
            reasons.append(hit.reason)

        if oui:
            apply(oui)
        if ssid_hit:
            apply(ssid_hit, weight=1.0 if not oui else 1.05)

        bonus, bonus_reason = channel_bonus(entry.channel, entry.band)
        if bonus:
            score = min(100, score + bonus)
            reasons.append(bonus_reason)

        # Hidden SSID soft-AP on 5 GHz with strong signal — mildly suspicious
        if not entry.ssid and entry.band in ("5", "5.8") and entry.rssi > -55:
            score = min(100, score + 12)
            reasons.append("Hidden SSID + strong 5 GHz signal")
            if category == "UNKNOWN":
                category = "IOT_CAMERA"

        # Soft-AP style: open/adhoc-looking capability + camera-like name already scored
        if entry.ssid and len(entry.ssid) <= 4 and entry.rssi > -50:
            score = min(100, score + 5)
            reasons.append("Very short SSID + strong RSSI")

        if category == "UNKNOWN" and score < 25:
            category = "STANDARD_AP"
            vendor = vendor if vendor != "Unknown" else "Wi-Fi AP"
            reasons.append("Looks like a standard access point")

        # RSSI variance can indicate motion / active streaming device nearby
        var = smoother.variance()
        if var > 12 and score >= 40:
            score = min(100, score + 6)
            reasons.append(f"High RSSI variance ({var:.1f}) — active / moving TX")

        hist = [v for _, v in smoother.history][-40:]
        device = ClassifiedDevice(
            bssid=key,
            ssid=entry.ssid or "(hidden)",
            rssi=entry.rssi,
            rssi_smooth=round(smooth, 1),
            distance_m=round(rssi_to_meters(int(round(smooth))), 2),
            channel=entry.channel,
            band=entry.band,
            frequency_mhz=entry.frequency_khz // 1000 if entry.frequency_khz else 0,
            phy_type=entry.phy_type,
            category=category,
            category_label=CATEGORY_LABELS.get(category, category),
            vendor=vendor,
            score=int(min(100, max(0, score))),
            reasons=reasons,
            angle_deg=round(self._angle_for(key, entry.channel), 1),
            first_seen=self._first_seen[key],
            last_seen=now,
            source=entry.source,
            rssi_history=[round(v, 1) for v in hist],
        )
        self._devices[key] = device
        return device

    def merge_lan(self, hosts: list[LanHost], now: Optional[float] = None) -> None:
        now = now or time.time()
        by_mac = {h.mac.upper(): h for h in hosts}
        for mac, host in by_mac.items():
            if mac in self._devices:
                d = self._devices[mac]
                d.lan_ip = host.ip
                d.open_ports = host.open_camera_ports
                if host.suspicion:
                    d.score = min(100, max(d.score, d.score // 2 + host.suspicion // 2))
                    d.reasons.extend(host.reasons)
                    if host.open_camera_ports and d.category in (
                        "UNKNOWN",
                        "STANDARD_AP",
                        "ROUTER",
                        "IOT_SENSOR",
                    ):
                        d.category = "IP_CAMERA"
                        d.category_label = CATEGORY_LABELS["IP_CAMERA"]
                d.last_seen = now
            elif host.suspicion >= 40 or host.open_camera_ports:
                key = mac
                if key not in self._first_seen:
                    self._first_seen[key] = now
                category = "IP_CAMERA" if host.open_camera_ports else "IOT_CAMERA"
                if host.vendor_hint and "DJI" in host.vendor_hint.upper():
                    category = "DRONE"
                self._devices[key] = ClassifiedDevice(
                    bssid=key,
                    ssid=f"LAN {host.ip}",
                    rssi=-70,
                    rssi_smooth=-70.0,
                    distance_m=rssi_to_meters(-70),
                    channel=0,
                    band="lan",
                    frequency_mhz=0,
                    phy_type="ethernet",
                    category=category,
                    category_label=CATEGORY_LABELS.get(category, category),
                    vendor=host.vendor_hint or "LAN host",
                    score=min(100, host.suspicion),
                    reasons=host.reasons or ["Discovered via ARP / port scan"],
                    angle_deg=round(self._angle_for(key, 1), 1),
                    first_seen=self._first_seen[key],
                    last_seen=now,
                    source="lan",
                    lan_ip=host.ip,
                    open_ports=host.open_camera_ports,
                )

    def prune(self, max_age_sec: float = 45.0, now: Optional[float] = None) -> None:
        now = now or time.time()
        stale = [k for k, d in self._devices.items() if now - d.last_seen > max_age_sec]
        for k in stale:
            self._devices.pop(k, None)

    def devices(self, min_score: int = 0) -> list[ClassifiedDevice]:
        items = [d for d in self._devices.values() if d.score >= min_score]
        items.sort(key=lambda d: (d.score, -d.rssi_smooth), reverse=True)
        return items

    def get(self, bssid: str) -> Optional[ClassifiedDevice]:
        return self._devices.get(bssid.upper())


def generate_simulation_devices(now: Optional[float] = None) -> list[BssEntry]:
    """Synthetic airspace for demo mode (no adapter required)."""
    now = now or time.time()
    # Gentle RSSI oscillation so Geiger / waterfall feel alive
    t = now
    def wobble(base: int, amp: float, speed: float) -> int:
        return int(base + amp * math.sin(t * speed))

    return [
        BssEntry(
            bssid="60:60:1F:A1:B2:C3",
            ssid="DJI-MINI3-8841",
            rssi=wobble(-48, 6, 0.7),
            link_quality=70,
            frequency_khz=5_745_000,
            channel=149,
            band="5.8",
            phy_type="vht",
            capability=0x0431,
            beacon_period=100,
            source="simulation",
        ),
        BssEntry(
            bssid="7C:49:EB:11:22:33",
            ssid="V380_A92F",
            rssi=wobble(-62, 8, 1.1),
            link_quality=45,
            frequency_khz=2_437_000,
            channel=6,
            band="2.4",
            phy_type="ht",
            capability=0x0431,
            beacon_period=100,
            source="simulation",
        ),
        BssEntry(
            bssid="24:0A:C4:DE:AD:01",
            ssid="ESP-CAM-bedroom",
            rssi=wobble(-55, 5, 0.9),
            link_quality=55,
            frequency_khz=2_462_000,
            channel=11,
            band="2.4",
            phy_type="ht",
            capability=0x0411,
            beacon_period=100,
            source="simulation",
        ),
        BssEntry(
            bssid="44:19:B6:44:55:66",
            ssid="HIKVISION-DVR",
            rssi=wobble(-71, 3, 0.4),
            link_quality=30,
            frequency_khz=5_180_000,
            channel=36,
            band="5",
            phy_type="vht",
            capability=0x1531,
            beacon_period=100,
            source="simulation",
        ),
        BssEntry(
            bssid="B0:B4:48:77:88:99",
            ssid="AUTEL-EVO-II",
            rssi=wobble(-58, 10, 1.4),
            link_quality=50,
            frequency_khz=5_825_000,
            channel=165,
            band="5.8",
            phy_type="vht",
            capability=0x0431,
            beacon_period=100,
            source="simulation",
        ),
        BssEntry(
            bssid="50:C7:BF:AA:BB:CC",
            ssid="HomeRouter-5G",
            rssi=wobble(-40, 2, 0.3),
            link_quality=90,
            frequency_khz=5_500_000,
            channel=100,
            band="5",
            phy_type="vht",
            capability=0x1531,
            beacon_period=100,
            source="simulation",
        ),
        BssEntry(
            bssid="F4:F2:6D:12:34:56",
            ssid="HomeRouter-2.4",
            rssi=wobble(-35, 2, 0.25),
            link_quality=95,
            frequency_khz=2_412_000,
            channel=1,
            band="2.4",
            phy_type="ht",
            capability=0x1531,
            beacon_period=100,
            source="simulation",
        ),
        BssEntry(
            bssid="EC:71:DB:98:76:54",
            ssid="Reolink_E1_Pro",
            rssi=wobble(-66, 4, 0.6),
            link_quality=40,
            frequency_khz=5_220_000,
            channel=44,
            band="5",
            phy_type="ht",
            capability=0x0431,
            beacon_period=100,
            source="simulation",
        ),
    ]
