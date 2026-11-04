"""Wi-Fi BSS scanner backend.

Enumerates adapters (including Gembird WNP-UA1300-02 / RTL8812BU),
triggers WlanScan, and returns BSSID / SSID / RSSI / channel / frequency.
Uses:
- Windows: wlanapi.dll, with netsh fallback
- Linux: nmcli (NetworkManager), with iw fallback
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

ERROR_SUCCESS = 0
ERROR_ACCESS_DENIED = 5
ERROR_NOT_FOUND = 1168
ERROR_INVALID_PARAMETER = 87

LOCATION_HELP = (
    "Windows blocked Wi-Fi scanning because Location is off. "
    "Enable Location: Settings > Privacy & security > Location "
    "(or run: start ms-settings:privacy-location), turn on "
    "'Location services' and allow desktop apps. Then click Scan again."
)

DOT11_BSS_TYPE_INFRASTRUCTURE = 1
DOT11_BSS_TYPE_INDEPENDENT = 2
DOT11_BSS_TYPE_ANY = 3

DOT11_PHY_TYPE_UNKNOWN = 0
DOT11_PHY_TYPE_ANY = 0
DOT11_PHY_TYPE_FHSS = 1
DOT11_PHY_TYPE_DSSS = 2
DOT11_PHY_TYPE_IRBASEBAND = 3
DOT11_PHY_TYPE_OFDM = 4
DOT11_PHY_TYPE_HRDSSS = 5
DOT11_PHY_TYPE_ERP = 6
DOT11_PHY_TYPE_HT = 7
DOT11_PHY_TYPE_VHT = 8


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def to_str(self) -> str:
        d4 = "".join(f"{b:02x}" for b in self.Data4)
        return (
            f"{{{self.Data1:08x}-{self.Data2:04x}-{self.Data3:04x}-"
            f"{d4[:4]}-{d4[4:]}}}"
        ).upper()


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [
        ("InterfaceGuid", GUID),
        ("strInterfaceDescription", ctypes.c_wchar * 256),
        ("isState", wintypes.DWORD),
    ]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", wintypes.DWORD),
        ("dwIndex", wintypes.DWORD),
        ("InterfaceInfo", WLAN_INTERFACE_INFO * 1),
    ]


class DOT11_SSID(ctypes.Structure):
    _fields_ = [
        ("uSSIDLength", wintypes.ULONG),
        ("ucSSID", ctypes.c_ubyte * 32),
    ]


class WLAN_RATE_SET(ctypes.Structure):
    _fields_ = [
        ("uRateSetLength", wintypes.ULONG),
        ("usRateSet", wintypes.USHORT * 126),
    ]


class WLAN_BSS_ENTRY(ctypes.Structure):
    _fields_ = [
        ("dot11Ssid", DOT11_SSID),
        ("uPhyId", wintypes.ULONG),
        ("dot11Bssid", ctypes.c_ubyte * 6),
        ("dot11BssType", wintypes.DWORD),
        ("dot11BssPhyType", wintypes.DWORD),
        ("lRssi", ctypes.c_long),
        ("uLinkQuality", wintypes.ULONG),
        ("bInRegDomain", wintypes.BOOLEAN),
        ("usBeaconPeriod", wintypes.USHORT),
        ("ullTimestamp", ctypes.c_ulonglong),
        ("ullHostTimestamp", ctypes.c_ulonglong),
        ("usCapabilityInformation", wintypes.USHORT),
        ("ulChCenterFrequency", wintypes.ULONG),
        ("wlanRateSet", WLAN_RATE_SET),
        ("ulIeOffset", wintypes.ULONG),
        ("ulIeSize", wintypes.ULONG),
    ]


class WLAN_BSS_LIST(ctypes.Structure):
    _fields_ = [
        ("dwTotalSize", wintypes.DWORD),
        ("dwNumberOfItems", wintypes.DWORD),
        ("wlanBssEntries", WLAN_BSS_ENTRY * 1),
    ]


@dataclass
class AdapterInfo:
    guid: str
    description: str
    state: int
    preferred: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BssEntry:
    bssid: str
    ssid: str
    rssi: int
    link_quality: int
    frequency_khz: int
    channel: int
    band: str
    phy_type: str
    capability: int
    beacon_period: int
    ie_hex: str = ""
    source: str = "wlanapi"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanResult:
    adapter: Optional[AdapterInfo]
    networks: list[BssEntry] = field(default_factory=list)
    scanned_at: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter.to_dict() if self.adapter else None,
            "networks": [n.to_dict() for n in self.networks],
            "scanned_at": self.scanned_at,
            "error": self.error,
        }


PREFERRED_ADAPTER_HINTS = (
    "wnp-ua1300",
    "gembird",
    "8812",
    "8822",
    "rtl88",
    "realtek 8812",
    "realtek 8822",
    "802.11ac",
    "usb",
)


def _signal_pct_to_rssi(signal_pct: int) -> int:
    """Approximate RSSI from quality percentage."""
    return -100 + int(max(0, min(100, signal_pct)) * 0.7)


def _freq_khz_to_channel(freq_khz: int) -> tuple[int, str]:
    """Convert center frequency (kHz) to channel number and band label."""
    if freq_khz <= 0:
        return 0, "unknown"
    mhz = freq_khz // 1000
    if 2400 <= mhz <= 2500:
        ch = max(1, min(14, (mhz - 2407) // 5))
        return ch, "2.4"
    if 5000 <= mhz <= 5900:
        ch = (mhz - 5000) // 5
        band = "5.8" if mhz >= 5725 else "5"
        return ch, band
    if 5925 <= mhz <= 7125:
        ch = (mhz - 5950) // 5
        return ch, "6"
    return 0, "unknown"


def _phy_name(phy: int) -> str:
    return {
        0: "unknown",
        1: "fhss",
        2: "dsss",
        3: "ir",
        4: "ofdm",
        5: "hrdsss",
        6: "erp",
        7: "ht",
        8: "vht",
        9: "he",
    }.get(phy, f"phy_{phy}")


def _mac_bytes(raw: ctypes.Array) -> str:
    return ":".join(f"{b:02X}" for b in raw)


def _ssid_bytes(ssid: DOT11_SSID) -> str:
    length = min(int(ssid.uSSIDLength), 32)
    try:
        return bytes(ssid.ucSSID[:length]).decode("utf-8", errors="replace")
    except Exception:
        return ""


class WlanApi:
    """Thin wrapper around wlanapi.dll."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("wlanapi is Windows-only")
        self._dll = ctypes.WinDLL("wlanapi.dll")
        self._handle = wintypes.HANDLE()
        self._opened = False

        self._dll.WlanOpenHandle.argtypes = [
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.HANDLE),
        ]
        self._dll.WlanOpenHandle.restype = wintypes.DWORD

        self._dll.WlanCloseHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        self._dll.WlanCloseHandle.restype = wintypes.DWORD

        self._dll.WlanEnumInterfaces.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)),
        ]
        self._dll.WlanEnumInterfaces.restype = wintypes.DWORD

        self._dll.WlanScan.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(GUID),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._dll.WlanScan.restype = wintypes.DWORD

        self._dll.WlanGetNetworkBssList.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(GUID),
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.BOOL,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.POINTER(WLAN_BSS_LIST)),
        ]
        self._dll.WlanGetNetworkBssList.restype = wintypes.DWORD

        self._dll.WlanFreeMemory.argtypes = [ctypes.c_void_p]
        self._dll.WlanFreeMemory.restype = None

    def open(self) -> None:
        if self._opened:
            return
        negotiated = wintypes.DWORD()
        rc = self._dll.WlanOpenHandle(
            2, None, ctypes.byref(negotiated), ctypes.byref(self._handle)
        )
        if rc != ERROR_SUCCESS:
            raise OSError(f"WlanOpenHandle failed: {rc}")
        self._opened = True

    def close(self) -> None:
        if self._opened:
            self._dll.WlanCloseHandle(self._handle, None)
            self._opened = False

    def __enter__(self) -> "WlanApi":
        self.open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def list_adapters(self) -> list[AdapterInfo]:
        self.open()
        ptr = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
        rc = self._dll.WlanEnumInterfaces(self._handle, None, ctypes.byref(ptr))
        if rc != ERROR_SUCCESS:
            raise OSError(f"WlanEnumInterfaces failed: {rc}")
        try:
            count = ptr.contents.dwNumberOfItems
            # Contiguous array after header
            info_array = ctypes.cast(
                ctypes.addressof(ptr.contents.InterfaceInfo),
                ctypes.POINTER(WLAN_INTERFACE_INFO * max(count, 1)),
            ).contents
            adapters: list[AdapterInfo] = []
            for i in range(count):
                item = info_array[i]
                desc = item.strInterfaceDescription
                preferred = any(h in desc.lower() for h in PREFERRED_ADAPTER_HINTS)
                adapters.append(
                    AdapterInfo(
                        guid=item.InterfaceGuid.to_str(),
                        description=desc,
                        state=int(item.isState),
                        preferred=preferred,
                    )
                )
            # Prefer USB / Realtek AC adapters
            adapters.sort(key=lambda a: (not a.preferred, a.description.lower()))
            return adapters
        finally:
            self._dll.WlanFreeMemory(ptr)

    def _guid_from_str(self, guid_str: str) -> GUID:
        cleaned = guid_str.strip("{}")
        parts = cleaned.split("-")
        if len(parts) != 5:
            raise ValueError(f"Invalid GUID: {guid_str}")
        g = GUID()
        g.Data1 = int(parts[0], 16)
        g.Data2 = int(parts[1], 16)
        g.Data3 = int(parts[2], 16)
        d4 = bytes.fromhex(parts[3] + parts[4])
        for i, b in enumerate(d4):
            g.Data4[i] = b
        return g

    def scan(self, adapter_guid: str, settle_seconds: float = 1.5) -> list[BssEntry]:
        self.open()
        guid = self._guid_from_str(adapter_guid)
        rc = self._dll.WlanScan(self._handle, ctypes.byref(guid), None, None, None)
        if rc == ERROR_ACCESS_DENIED:
            raise PermissionError(LOCATION_HELP)
        if rc not in (ERROR_SUCCESS,):
            # Other codes may still leave a usable BSS cache — continue
            pass
        time.sleep(max(0.3, settle_seconds))

        bss_ptr = ctypes.POINTER(WLAN_BSS_LIST)()
        rc = self._dll.WlanGetNetworkBssList(
            self._handle,
            ctypes.byref(guid),
            None,
            DOT11_BSS_TYPE_ANY,
            False,
            None,
            ctypes.byref(bss_ptr),
        )
        if rc == ERROR_ACCESS_DENIED:
            raise PermissionError(LOCATION_HELP)
        if rc != ERROR_SUCCESS:
            raise OSError(f"WlanGetNetworkBssList failed: {rc}")

        try:
            header = bss_ptr.contents
            total = int(header.dwNumberOfItems)
            total_size = int(header.dwTotalSize)
            entries: list[BssEntry] = []
            # Header is dwTotalSize + dwNumberOfItems (8 bytes); entries follow.
            list_base = ctypes.addressof(header)
            pos = 8
            fixed = ctypes.sizeof(WLAN_BSS_ENTRY)
            for _ in range(total):
                if pos + fixed > total_size:
                    break
                entry = WLAN_BSS_ENTRY.from_address(list_base + pos)
                freq = int(entry.ulChCenterFrequency)
                channel, band = _freq_khz_to_channel(freq)
                ie_hex = ""
                ie_off = int(entry.ulIeOffset)
                ie_size = int(entry.ulIeSize)
                if ie_size > 0 and ie_off > 0 and pos + ie_off + ie_size <= total_size:
                    ie_bytes = (ctypes.c_ubyte * ie_size).from_address(
                        list_base + pos + ie_off
                    )
                    ie_hex = bytes(ie_bytes).hex()
                entries.append(
                    BssEntry(
                        bssid=_mac_bytes(entry.dot11Bssid),
                        ssid=_ssid_bytes(entry.dot11Ssid),
                        rssi=int(entry.lRssi),
                        link_quality=int(entry.uLinkQuality),
                        frequency_khz=freq,
                        channel=channel,
                        band=band,
                        phy_type=_phy_name(int(entry.dot11BssPhyType)),
                        capability=int(entry.usCapabilityInformation),
                        beacon_period=int(entry.usBeaconPeriod),
                        ie_hex=ie_hex,
                        source="wlanapi",
                    )
                )
                stride = max(fixed, ie_off + ie_size)
                stride = (stride + 3) & ~3
                if stride <= 0:
                    break
                pos += stride
            return entries
        finally:
            self._dll.WlanFreeMemory(bss_ptr)


def _netsh_list_interfaces() -> list[AdapterInfo]:
    """Fallback adapter discovery via netsh."""
    try:
        out = subprocess.check_output(
            ["netsh", "wlan", "show", "interfaces"],
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception:
        return []
    adapters: list[AdapterInfo] = []
    name = ""
    guid = ""
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, val = [p.strip() for p in line.split(":", 1)]
        low = key.lower()
        if low in ("name", "имя", "nazwa"):
            if name and guid:
                preferred = any(h in name.lower() for h in PREFERRED_ADAPTER_HINTS)
                adapters.append(
                    AdapterInfo(guid=guid, description=name, state=1, preferred=preferred)
                )
            name, guid = val, ""
        elif "guid" in low:
            guid = val if val.startswith("{") else f"{{{val}}}"
    if name and guid:
        preferred = any(h in name.lower() for h in PREFERRED_ADAPTER_HINTS)
        adapters.append(AdapterInfo(guid=guid, description=name, state=1, preferred=preferred))
    return adapters


def _netsh_scan(adapter_name: Optional[str] = None) -> list[BssEntry]:
    """Fallback BSS scan via `netsh wlan show networks mode=bssid`."""
    cmd = ["netsh", "wlan", "show", "networks", "mode=bssid"]
    if adapter_name:
        cmd.append(f'interface="{adapter_name}"')
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
            check=False,
        )
    except Exception as exc:
        raise OSError(f"netsh scan failed: {exc}") from exc

    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    low = blob.lower()
    if proc.returncode != 0:
        if "location" in low or "местополож" in low or "расположен" in low:
            raise PermissionError(LOCATION_HELP)
        raise OSError(f"netsh scan failed ({proc.returncode}): {blob.strip()[:300]}")
    out = proc.stdout or ""

    networks: list[BssEntry] = []
    ssid = ""
    bssid = ""
    signal = 0
    channel = 0
    radio = ""

    def flush() -> None:
        nonlocal bssid
        if not bssid:
            return
        # netsh signal is percent; approximate RSSI
        rssi = _signal_pct_to_rssi(signal)
        band = "2.4"
        freq = 2412
        if channel >= 36:
            band = "5.8" if channel >= 149 else "5"
            freq = 5000 + channel * 5
        elif channel > 0:
            freq = 2407 + channel * 5
        networks.append(
            BssEntry(
                bssid=bssid.upper(),
                ssid=ssid,
                rssi=rssi,
                link_quality=int(signal),
                frequency_khz=freq * 1000,
                channel=channel,
                band=band,
                phy_type=radio.lower() or "unknown",
                capability=0,
                beacon_period=0,
                source="netsh",
            )
        )
        bssid = ""

    for raw in out.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, val = [p.strip() for p in line.split(":", 1)]
        low = key.lower()
        if low.startswith("ssid") and not low.startswith("bssid"):
            flush()
            # "SSID 1 : MyNet"
            ssid = val
        elif "bssid" in low:
            flush()
            bssid = val.upper()
        elif "signal" in low or "сигнал" in low:
            m = re.search(r"(\d+)", val)
            signal = int(m.group(1)) if m else 0
        elif "channel" in low or "канал" in low:
            m = re.search(r"(\d+)", val)
            channel = int(m.group(1)) if m else 0
        elif "radio" in low or "тип" in low:
            radio = val
    flush()
    return networks


def _split_nmcli_escaped(line: str) -> list[str]:
    """Split a colon-separated nmcli terse line while honoring escaped colons."""
    parts: list[str] = []
    cur: list[str] = []
    esc = False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == ":":
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur))
    return parts


def _linux_list_interfaces() -> list[AdapterInfo]:
    """List Wi-Fi interfaces via NetworkManager."""
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return []
    adapters: list[AdapterInfo] = []
    for raw in out.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = _split_nmcli_escaped(raw)
        if len(parts) < 3:
            continue
        dev, dev_type, state = parts[0], parts[1].lower(), parts[2].lower()
        if dev_type != "wifi":
            continue
        preferred = any(h in dev.lower() for h in PREFERRED_ADAPTER_HINTS) or dev.startswith(
            "wl"
        )
        state_num = 1 if state in ("connected", "disconnected", "connecting") else 0
        adapters.append(
            AdapterInfo(
                guid=dev,
                description=f"Linux Wi-Fi ({dev})",
                state=state_num,
                preferred=preferred,
            )
        )
    adapters.sort(key=lambda a: (not a.preferred, a.description.lower()))
    return adapters


def _linux_scan_nmcli(interface_name: Optional[str] = None) -> list[BssEntry]:
    """Scan Wi-Fi networks via nmcli."""
    cmd = [
        "nmcli",
        "-t",
        "-f",
        "BSSID,SSID,SIGNAL,CHAN,FREQ,RATE,SECURITY",
        "device",
        "wifi",
        "list",
        "--rescan",
        "yes",
    ]
    if interface_name:
        cmd += ["ifname", interface_name]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
        raise OSError(f"nmcli scan failed ({proc.returncode}): {blob.strip()[:300]}")

    networks: list[BssEntry] = []
    for raw in (proc.stdout or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = _split_nmcli_escaped(line)
        if len(parts) < 7:
            continue
        bssid = parts[0].upper()
        ssid = parts[1]
        try:
            signal = int(parts[2] or "0")
        except ValueError:
            signal = 0
        try:
            channel = int(parts[3] or "0")
        except ValueError:
            channel = 0
        try:
            freq_mhz = int(parts[4] or "0")
        except ValueError:
            freq_mhz = 0
        freq_khz = freq_mhz * 1000 if freq_mhz > 0 else 0
        if channel <= 0 and freq_khz > 0:
            channel, band = _freq_khz_to_channel(freq_khz)
        else:
            _ch, band = _freq_khz_to_channel(freq_khz) if freq_khz > 0 else (channel, "unknown")
        security = parts[6].lower()
        phy_type = "open" if security in ("", "--") else "secured"
        networks.append(
            BssEntry(
                bssid=bssid,
                ssid=ssid,
                rssi=_signal_pct_to_rssi(signal),
                link_quality=signal,
                frequency_khz=freq_khz,
                channel=channel,
                band=band,
                phy_type=phy_type,
                capability=0,
                beacon_period=0,
                source="nmcli",
            )
        )
    return networks


class WifiScanner:
    """High-level scanner with hot-plug aware adapter selection."""

    def __init__(self) -> None:
        self._api: Optional[WlanApi] = None
        self._selected_guid: Optional[str] = None
        self._use_netsh = False
        self._linux_mode = sys.platform.startswith("linux")
        if sys.platform == "win32":
            try:
                self._api = WlanApi()
                self._api.open()
            except Exception:
                self._api = None
                self._use_netsh = True
        else:
            self._use_netsh = True

    def close(self) -> None:
        if self._api:
            self._api.close()

    def list_adapters(self) -> list[AdapterInfo]:
        if self._linux_mode:
            return _linux_list_interfaces()
        if self._api and not self._use_netsh:
            try:
                return self._api.list_adapters()
            except Exception:
                self._use_netsh = True
        return _netsh_list_interfaces()

    def select_adapter(self, guid_or_desc: Optional[str] = None) -> Optional[AdapterInfo]:
        adapters = self.list_adapters()
        if not adapters:
            self._selected_guid = None
            return None
        if guid_or_desc:
            target = guid_or_desc.strip().lower()
            for a in adapters:
                if (
                    a.guid.lower() == target
                    or target in a.description.lower()
                    or a.guid.lower().strip("{}") == target.strip("{}")
                ):
                    self._selected_guid = a.guid
                    return a
        # Auto-prefer USB Realtek / WNP-UA1300, else first
        for a in adapters:
            if a.preferred:
                self._selected_guid = a.guid
                return a
        self._selected_guid = adapters[0].guid
        return adapters[0]

    def get_selected(self) -> Optional[AdapterInfo]:
        adapters = self.list_adapters()
        for a in adapters:
            if a.guid == self._selected_guid:
                return a
        return None

    def scan(self, settle_seconds: float = 1.2) -> ScanResult:
        adapter = self.get_selected() or self.select_adapter()
        now = time.time()
        if not adapter:
            return ScanResult(
                adapter=None,
                networks=[],
                scanned_at=now,
                error="No Wi-Fi adapter found. Plug in WNP-UA1300-02 or enable Simulation Mode.",
            )
        try:
            if self._linux_mode:
                nets = _linux_scan_nmcli(adapter.guid)
            elif self._api and not self._use_netsh:
                nets = self._api.scan(adapter.guid, settle_seconds=settle_seconds)
            else:
                nets = _netsh_scan(adapter.description)
            best: dict[str, BssEntry] = {}
            for n in nets:
                key = n.bssid.upper()
                if key not in best or n.rssi > best[key].rssi:
                    best[key] = n
            return ScanResult(
                adapter=adapter,
                networks=list(best.values()),
                scanned_at=now,
                error=None,
            )
        except PermissionError as exc:
            # Location / privacy block — do not mask the message
            return ScanResult(
                adapter=adapter,
                networks=[],
                scanned_at=now,
                error=str(exc),
            )
        except Exception as exc:
            try:
                nets = _linux_scan_nmcli(adapter.guid) if self._linux_mode else _netsh_scan(adapter.description)
                return ScanResult(
                    adapter=adapter,
                    networks=nets,
                    scanned_at=now,
                    error=f"scan backend error (used fallback): {exc}",
                )
            except PermissionError as exc2:
                return ScanResult(
                    adapter=adapter,
                    networks=[],
                    scanned_at=now,
                    error=str(exc2),
                )
            except Exception as exc2:
                return ScanResult(
                    adapter=adapter,
                    networks=[],
                    scanned_at=now,
                    error=str(exc2),
                )
