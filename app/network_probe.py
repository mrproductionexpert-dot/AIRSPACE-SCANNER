"""LAN ARP / camera-port / traffic-burst probing helpers."""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import psutil

from .signatures import CAMERA_PORTS, lookup_oui


@dataclass
class LanHost:
    ip: str
    mac: str
    vendor_hint: str = ""
    open_camera_ports: list[int] = field(default_factory=list)
    bytes_per_sec: float = 0.0
    packets_per_sec: float = 0.0
    suspicion: int = 0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrafficSnapshot:
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int
    ts: float


class NetworkProbe:
    """Passive-ish LAN probe: ARP table + port checks + NIC byte-rate deltas."""

    def __init__(self) -> None:
        self._prev_nic: dict[str, TrafficSnapshot] = {}
        self._host_rates: dict[str, tuple[float, float]] = {}

    def arp_table(self) -> list[tuple[str, str]]:
        """Return list of (ip, mac) from the system ARP cache."""
        rows: list[tuple[str, str]] = []
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            out = subprocess.check_output(
                ["arp", "-a"],
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=flags,
            )
        except Exception:
            return rows

        # Windows:  192.168.1.1    00-11-22-33-44-55    dynamic
        # Unix:     192.168.1.1    ether 00:11:22:33:44:55   C
        pattern = re.compile(
            r"(\d{1,3}(?:\.\d{1,3}){3})\s+.*?([0-9a-fA-F]{2}(?:[-:][0-9a-fA-F]{2}){5})"
        )
        for line in out.splitlines():
            m = pattern.search(line)
            if not m:
                continue
            ip, mac = m.group(1), m.group(2).upper().replace("-", ":")
            if mac in ("FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00"):
                continue
            if ip.endswith(".255") or ip.startswith("224."):
                continue
            rows.append((ip, mac))
        return rows

    def probe_camera_ports(self, ip: str, timeout: float = 0.25) -> list[int]:
        open_ports: list[int] = []
        for port in CAMERA_PORTS:
            try:
                with socket.create_connection((ip, port), timeout=timeout):
                    open_ports.append(port)
            except OSError:
                continue
        return open_ports

    def nic_burst_stats(self) -> dict[str, dict[str, float]]:
        """Per-NIC byte/packet rates since last call."""
        stats = psutil.net_io_counters(pernic=True)
        now = time.time()
        result: dict[str, dict[str, float]] = {}
        for name, counters in stats.items():
            snap = TrafficSnapshot(
                bytes_sent=counters.bytes_sent,
                bytes_recv=counters.bytes_recv,
                packets_sent=counters.packets_sent,
                packets_recv=counters.packets_recv,
                ts=now,
            )
            prev = self._prev_nic.get(name)
            self._prev_nic[name] = snap
            if not prev:
                result[name] = {
                    "bytes_per_sec": 0.0,
                    "packets_per_sec": 0.0,
                    "recv_bps": 0.0,
                    "sent_bps": 0.0,
                }
                continue
            dt = max(0.001, now - prev.ts)
            recv_bps = (snap.bytes_recv - prev.bytes_recv) / dt
            sent_bps = (snap.bytes_sent - prev.bytes_sent) / dt
            pkt_ps = (
                (snap.packets_recv - prev.packets_recv)
                + (snap.packets_sent - prev.packets_sent)
            ) / dt
            result[name] = {
                "bytes_per_sec": recv_bps + sent_bps,
                "packets_per_sec": pkt_ps,
                "recv_bps": recv_bps,
                "sent_bps": sent_bps,
            }
        return result

    def scan_lan(self, deep_ports: bool = True, max_hosts: int = 32) -> list[LanHost]:
        hosts: list[LanHost] = []
        nic_stats = self.nic_burst_stats()
        # Aggregate burstiness across physical NICs (ignore loopback / virtual)
        burst_bps = 0.0
        burst_pps = 0.0
        for name, s in nic_stats.items():
            low = name.lower()
            if any(x in low for x in ("loopback", "vethernet", "hyper-v", "bluetooth")):
                continue
            burst_bps = max(burst_bps, s["bytes_per_sec"])
            burst_pps = max(burst_pps, s["packets_per_sec"])

        for ip, mac in self.arp_table()[:max_hosts]:
            reasons: list[str] = []
            suspicion = 0
            vendor = ""
            oui_hit = lookup_oui(mac)
            if oui_hit:
                vendor = oui_hit.vendor
                if oui_hit.category in ("DRONE", "HIDDEN_CAM", "IP_CAMERA", "IOT_CAMERA"):
                    suspicion += oui_hit.score // 2
                    reasons.append(oui_hit.reason)

            ports: list[int] = []
            if deep_ports:
                ports = self.probe_camera_ports(ip)
                if ports:
                    suspicion += 35 + min(20, 5 * len(ports))
                    reasons.append(f"Open camera ports: {ports}")

            # Attribute global burst to hosts that look camera-like
            bps = 0.0
            pps = 0.0
            if ports or (oui_hit and oui_hit.category.endswith("CAMERA")):
                bps = burst_bps
                pps = burst_pps
                if burst_bps > 200_000:  # ~1.6 Mbps — typical video stream
                    suspicion += 25
                    reasons.append(f"High traffic burst ~{burst_bps/1000:.0f} KB/s")
                elif burst_bps > 50_000:
                    suspicion += 10
                    reasons.append(f"Elevated traffic ~{burst_bps/1000:.0f} KB/s")

            hosts.append(
                LanHost(
                    ip=ip,
                    mac=mac,
                    vendor_hint=vendor,
                    open_camera_ports=ports,
                    bytes_per_sec=bps,
                    packets_per_sec=pps,
                    suspicion=min(100, suspicion),
                    reasons=reasons,
                )
            )
        hosts.sort(key=lambda h: h.suspicion, reverse=True)
        return hosts


def local_ipv4_addresses() -> list[str]:
    addrs: list[str] = []
    for _name, snics in psutil.net_if_addrs().items():
        for snic in snics:
            if snic.family == socket.AF_INET and not snic.address.startswith("127."):
                addrs.append(snic.address)
    return addrs
