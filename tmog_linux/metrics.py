from __future__ import annotations

import csv
import configparser
import glob
import ipaddress
import os
import platform
import re
import signal
import shutil
import socket
import struct
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

try:
    import pwd
except ImportError:  # Allows parser tests to run on non-POSIX development hosts.
    pwd = None  # type: ignore[assignment]

try:
    import fcntl
except ImportError:  # Linux-only network address lookup.
    fcntl = None  # type: ignore[assignment]


@dataclass(slots=True)
class ProcessInfo:
    pid: int
    ppid: int
    name: str
    command: str
    user: str
    state: str
    cpu_percent: float
    memory_bytes: int
    threads: int
    read_bytes: int
    write_bytes: int
    started_at: float
    swap_bytes: int = 0
    user_cpu_seconds: float = 0.0
    system_cpu_seconds: float = 0.0
    control_group: str = "/"


@dataclass(slots=True)
class GpuSnapshot:
    identifier: str
    name: str
    utilization: float | None
    utilization_source: str
    driver: str
    pci_id: str
    pci_address: str
    device_nodes: str
    frequency_mhz: float | None
    frequency_max_mhz: float | None
    memory_mode: str
    memory_total: int | None
    memory_used: int | None
    temperature_c: float | None = None
    power_watts: float | None = None
    fan_percent: float | None = None


@dataclass(slots=True)
class DiskSnapshot:
    identifier: str
    model: str
    device_type: str
    busy_percent: float
    read_bps: float
    write_bps: float
    read_total: int
    write_total: int
    capacity: int
    used: int | None = None
    free: int | None = None


@dataclass(slots=True)
class NetworkInterfaceSnapshot:
    identifier: str
    connection_type: str
    state: str
    link_speed_mbps: int | None
    receive_bps: float
    send_bps: float
    receive_total: int
    send_total: int
    hardware_address: str
    ipv4_addresses: str
    ipv6_addresses: str
    mtu: int | None
    primary: bool = False


@dataclass(slots=True)
class ThermalSensor:
    identifier: str
    label: str
    temperature_c: float
    source: str


@dataclass(slots=True)
class SystemSnapshot:
    timestamp: float
    cpu_percent: float
    per_cpu_percent: list[float]
    kernel_percent: float
    cpu_mhz: float | None
    cpu_max_mhz: float | None
    cpu_model: str
    cpu_physical_cores: int
    cpu_core_types: list[str]
    cpu_cache_summary: str
    context_switches: int
    interrupts: int
    memory_total: int
    memory_used: int
    memory_available: int
    memory_cached: int
    memory_active: int
    memory_inactive: int
    memory_buffers: int
    memory_slab: int
    memory_committed: int
    memory_shared: int
    memory_pressure_percent: float
    swap_total: int
    swap_used: int
    disk_read_bps: float
    disk_write_bps: float
    disk_busy_percent: float
    disk_read_total: int
    disk_write_total: int
    disk_device_count: int
    disk_capacity: int
    disk_used: int
    disk_free: int
    disks: list[DiskSnapshot]
    network_receive_bps: float
    network_send_bps: float
    network_receive_total: int
    network_send_total: int
    network_interface_count: int
    primary_interface: str
    link_speed_mbps: int | None
    network_connection_type: str
    network_hardware_address: str
    network_ipv4_addresses: str
    network_ipv6_addresses: str
    network_mtu: int | None
    network_state: str
    network_interfaces: list[NetworkInterfaceSnapshot]
    temperature_c: float | None
    thermal_sensor_count: int
    thermal_sensors: list[ThermalSensor]
    gpu_percent: float | None
    gpu_name: str
    gpu_memory_total: int | None
    gpu_memory_used: int | None
    gpu_driver: str
    gpu_pci_id: str
    gpu_pci_address: str
    gpu_render_nodes: str
    gpu_frequency_mhz: float | None
    gpu_frequency_max_mhz: float | None
    gpu_memory_mode: str
    gpu_utilization_source: str
    gpus: list[GpuSnapshot]
    npu_name: str | None
    power_watts: float | None
    cpu_package_watts: float | None
    gpu_power_watts: float | None
    observed_power_watts: float | None
    power_source: str
    battery_status: str
    battery_percent: float | None
    uptime_seconds: float
    process_count: int
    thread_count: int
    file_handle_count: int
    load_average: tuple[float, float, float]
    processes: list[ProcessInfo] = field(default_factory=list)


@dataclass(slots=True)
class StartupEntry:
    name: str
    command: str
    source: str
    enabled: bool
    desktop_file: Path


@dataclass(slots=True)
class ServiceInfo:
    unit: str
    active: str
    state: str
    description: str


CPU_FIELDS = ("user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal")
STATE_NAMES = {
    "R": "Running",
    "S": "Sleeping",
    "D": "Disk wait",
    "Z": "Zombie",
    "T": "Stopped",
    "t": "Tracing",
    "I": "Idle",
    "X": "Dead",
}

NVIDIA_QUERY_FIELDS = (
    "index",
    "name",
    "pci.bus_id",
    "pci.device_id",
    "driver_version",
    "utilization.gpu",
    "memory.used",
    "memory.total",
    "clocks.gr",
    "clocks.max.graphics",
    "temperature.gpu",
    "power.draw",
    "fan.speed",
)
NVIDIA_FALLBACK_FIELDS = NVIDIA_QUERY_FIELDS[:8] + ("temperature.gpu",)


def parse_cpu_stat(text: str) -> dict[str, tuple[int, ...]]:
    result: dict[str, tuple[int, ...]] = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts or not re.fullmatch(r"cpu\d*", parts[0]):
            continue
        values = tuple(int(value) for value in parts[1:9])
        if len(values) < 8:
            values += (0,) * (8 - len(values))
        result[parts[0]] = values
    return result


def cpu_percent(previous: tuple[int, ...], current: tuple[int, ...]) -> tuple[float, float]:
    deltas = [max(0, new - old) for old, new in zip(previous, current)]
    total = sum(deltas)
    if total <= 0:
        return 0.0, 0.0
    idle = deltas[3] + deltas[4]
    busy = total - idle
    kernel = deltas[2] + deltas[5] + deltas[6]
    return 100.0 * busy / total, 100.0 * kernel / total


def parse_meminfo(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        match = re.search(r"(\d+)", raw)
        if match:
            values[key] = int(match.group(1)) * 1024
    return values


def parse_diskstats_by_device(text: str, devices: set[str]) -> dict[str, tuple[int, int, int]]:
    values: dict[str, tuple[int, int, int]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 14 or parts[2] not in devices:
            continue
        values[parts[2]] = (int(parts[5]) * 512, int(parts[9]) * 512, int(parts[12]))
    return values


def parse_diskstats(text: str, devices: set[str]) -> tuple[int, int, int]:
    read_sectors = write_sectors = io_ms = 0
    for read_bytes, write_bytes, device_io_ms in parse_diskstats_by_device(text, devices).values():
        read_sectors += read_bytes
        write_sectors += write_bytes
        io_ms += device_io_ms
    return read_sectors, write_sectors, io_ms


def parse_netdev_interfaces(text: str) -> dict[str, tuple[int, int]]:
    interfaces: dict[str, tuple[int, int]] = {}
    for line in text.splitlines()[2:]:
        if ":" not in line:
            continue
        interface, values = line.split(":", 1)
        name = interface.strip()
        if name == "lo":
            continue
        fields = values.split()
        if len(fields) >= 9:
            interfaces[name] = (int(fields[0]), int(fields[8]))
    return interfaces


def parse_netdev(text: str) -> tuple[int, int]:
    received = sent = 0
    for interface_received, interface_sent in parse_netdev_interfaces(text).values():
        received += interface_received
        sent += interface_sent
    return received, sent


def parse_default_route_interface(text: str) -> str | None:
    candidates: list[tuple[int, str]] = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 8 or fields[1] != "00000000":
            continue
        try:
            flags = int(fields[3], 16)
            metric = int(fields[6])
        except ValueError:
            continue
        if flags & 0x1:
            candidates.append((metric, fields[0]))
    return min(candidates)[1] if candidates else None


def parse_pci_device_name(text: str, vendor_id: str, device_id: str) -> str | None:
    vendor_id = vendor_id.lower().removeprefix("0x")
    device_id = device_id.lower().removeprefix("0x")
    active_vendor = False
    vendor_name = ""
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if not line[0].isspace():
            fields = line.split(None, 1)
            active_vendor = bool(fields and fields[0].lower() == vendor_id)
            vendor_name = fields[1].strip() if active_vendor and len(fields) > 1 else ""
            continue
        if not active_vendor or line.startswith("\t\t"):
            continue
        fields = line.strip().split(None, 1)
        if fields and fields[0].lower() == device_id and len(fields) > 1:
            return f"{vendor_name} {fields[1].strip()}".strip()
    return None


def parse_drm_fdinfo(text: str) -> tuple[str, str, str, dict[str, int]]:
    driver = pdev = client_id = ""
    engines: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        value = raw.strip()
        if key == "drm-driver":
            driver = value
        elif key == "drm-pdev":
            pdev = value
        elif key == "drm-client-id":
            client_id = value
        elif key.startswith("drm-engine-"):
            match = re.match(r"(\d+)\s+ns\b", value)
            if match:
                engines[key.removeprefix("drm-engine-")] = int(match.group(1))
    return driver, pdev, client_id, engines


def parse_nvidia_smi_csv(text: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for values in csv.reader(text.splitlines()):
        if len(values) != len(fields):
            continue
        rows.append({key: value.strip() for key, value in zip(fields, values)})
    return rows


def parse_process_stat(text: str) -> dict[str, int | str]:
    close = text.rfind(")")
    open_ = text.find("(")
    if open_ < 0 or close < 0:
        raise ValueError("invalid /proc process stat")
    pid = int(text[:open_].strip())
    name = text[open_ + 1 : close]
    fields = text[close + 2 :].split()
    if len(fields) < 22:
        raise ValueError("incomplete /proc process stat")
    return {
        "pid": pid,
        "name": name,
        "state": fields[0],
        "ppid": int(fields[1]),
        "user_ticks": int(fields[11]),
        "system_ticks": int(fields[12]),
        "cpu_ticks": int(fields[11]) + int(fields[12]),
        "threads": int(fields[17]),
        "start_ticks": int(fields[19]),
        "rss_pages": int(fields[21]),
    }


def format_bytes(value: float, *, rate: bool = False) -> str:
    suffix = "/s" if rate else ""
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    number = max(0.0, float(value))
    for unit in units:
        if number < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{number:.0f} {unit}{suffix}"
            return f"{number:.1f} {unit}{suffix}"
        number /= 1024.0
    return f"0 B{suffix}"


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    return f"{hours:02d}h {minutes:02d}m"


class LinuxMetricsCollector:
    """Collect Linux metrics without shelling out on the hot path."""

    def __init__(self, proc_root: str | Path = "/proc", sys_root: str | Path = "/sys") -> None:
        self.proc_root = Path(proc_root)
        self.sys_root = Path(sys_root)
        self.clock_ticks = os.sysconf("SC_CLK_TCK")
        self.page_size = os.sysconf("SC_PAGE_SIZE")
        self.cpu_count = max(1, os.cpu_count() or 1)
        self._previous_cpu: dict[str, tuple[int, ...]] = {}
        self._previous_disks: dict[str, tuple[int, int, int]] = {}
        self._previous_networks: dict[str, tuple[int, int]] = {}
        self._previous_process_ticks: dict[int, int] = {}
        self._previous_gpu_counters: dict[tuple[str, str], int] = {}
        self._previous_rapl_energy: dict[str, int] = {}
        self._gpu_fd_paths: list[tuple[str, str]] = []
        self._last_gpu_fd_scan = 0.0
        self._previous_time: float | None = None
        self._physical_devices = self._find_physical_devices()
        self.cpu_model, self.cpu_physical_cores, self.cpu_max_mhz, self.cpu_cache_summary = self._read_cpu_topology()
        self.cpu_core_types = self._read_cpu_core_types()
        self._gpu_devices = self._gpu_device_paths()
        (
            self.gpu_driver,
            self.gpu_vendor_id,
            self.gpu_device_id,
            self.gpu_pci_address,
            self.gpu_render_nodes,
        ) = self._read_gpu_identity()
        self.gpu_pci_id = (
            f"{self.gpu_vendor_id.removeprefix('0x')}:{self.gpu_device_id.removeprefix('0x')}"
            if self.gpu_vendor_id and self.gpu_device_id
            else "N/A"
        )
        self.gpu_name = self._read_gpu_name()
        self.gpu_memory_mode = (
            "Shared system memory"
            if self.gpu_vendor_id == "0x8086"
            else "Dedicated VRAM"
            if self.gpu_vendor_id
            else "N/A"
        )
        wsl_nvidia_smi = Path("/usr/lib/wsl/lib/nvidia-smi")
        self._nvidia_smi_path = shutil.which("nvidia-smi") or (str(wsl_nvidia_smi) if wsl_nvidia_smi.exists() else None)
        self.npu_name = self._read_npu_name()

    def _read(self, relative: str, default: str = "") -> str:
        try:
            return (self.proc_root / relative).read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError):
            return default

    def _find_physical_devices(self) -> set[str]:
        block_root = self.sys_root / "block"
        try:
            return {
                item.name
                for item in block_root.iterdir()
                if not item.name.startswith(("loop", "ram", "zram", "fd"))
            }
        except OSError:
            return set()

    def _read_cpu_frequency(self) -> float | None:
        frequencies: list[float] = []
        pattern = str(self.sys_root / "devices/system/cpu/cpu*/cpufreq/scaling_cur_freq")
        for filename in glob.glob(pattern):
            try:
                frequencies.append(float(Path(filename).read_text().strip()) / 1000.0)
            except (OSError, ValueError):
                continue
        if frequencies:
            return sum(frequencies) / len(frequencies)
        matches = re.findall(r"cpu MHz\s*:\s*([0-9.]+)", self._read("cpuinfo"))
        return sum(map(float, matches)) / len(matches) if matches else None

    def _read_cpu_topology(self) -> tuple[str, int, float | None, str]:
        cpuinfo = self._read("cpuinfo")
        model_match = re.search(r"^(?:model name|Hardware|Processor)\s*:\s*(.+)$", cpuinfo, re.MULTILINE)
        model = model_match.group(1).strip() if model_match else platform.processor() or "Unknown processor"
        core_pairs: set[tuple[str, str]] = set()
        for record in re.split(r"\n\s*\n", cpuinfo):
            physical = re.search(r"^physical id\s*:\s*(\S+)", record, re.MULTILINE)
            core = re.search(r"^core id\s*:\s*(\S+)", record, re.MULTILINE)
            if physical and core:
                core_pairs.add((physical.group(1), core.group(1)))
        cores_match = re.search(r"^cpu cores\s*:\s*(\d+)", cpuinfo, re.MULTILINE)
        physical_cores = len(core_pairs) or (int(cores_match.group(1)) if cores_match else self.cpu_count)

        maximums: list[float] = []
        pattern = str(self.sys_root / "devices/system/cpu/cpu*/cpufreq/cpuinfo_max_freq")
        for filename in glob.glob(pattern):
            try:
                maximums.append(float(Path(filename).read_text().strip()) / 1000.0)
            except (OSError, ValueError):
                continue
        max_mhz = max(maximums) if maximums else None

        caches: list[str] = []
        cache_root = self.sys_root / "devices/system/cpu/cpu0/cache"
        for index in sorted(cache_root.glob("index*")):
            try:
                level = (index / "level").read_text().strip()
                cache_type = (index / "type").read_text().strip().lower()
                size = (index / "size").read_text().strip()
                suffix = "d" if cache_type == "data" else "i" if cache_type == "instruction" else ""
                caches.append(f"L{level}{suffix} {size}")
            except OSError:
                continue
        return model, max(1, physical_cores), max_mhz, "  •  ".join(caches) or "Cache details unavailable"

    def _read_cpu_core_types(self) -> list[str]:
        types: list[str] = []
        for index in range(self.cpu_count):
            path = self.sys_root / f"devices/system/cpu/cpu{index}/topology/core_type"
            try:
                raw = path.read_text().strip()
            except OSError:
                raw = ""
            types.append("E" if raw == "1" else "P" if raw == "2" else "")
        return types

    def _read_thermals(self) -> tuple[float | None, int, list[ThermalSensor]]:
        preferred: list[ThermalSensor] = []
        fallback: list[ThermalSensor] = []
        thermal_root = self.sys_root / "class/thermal"
        for path in thermal_root.glob("thermal_zone*"):
            try:
                value = float((path / "temp").read_text().strip())
                value = value / 1000.0 if value > 1000 else value
                if not 0 < value < 150:
                    continue
                sensor_type = (path / "type").read_text().strip()
                sensor = ThermalSensor(
                    identifier=f"thermal:{path.name}",
                    label=sensor_type.replace("_", " ") or path.name,
                    temperature_c=value,
                    source="thermal zone",
                )
                target = preferred if any(word in sensor_type.lower() for word in ("cpu", "pkg", "x86", "soc")) else fallback
                target.append(sensor)
            except (OSError, ValueError):
                continue
        hwmon_root = self.sys_root / "class/hwmon"
        for path in hwmon_root.glob("hwmon*"):
            try:
                device_name = (path / "name").read_text().strip()
            except OSError:
                device_name = ""
            for input_path in path.glob("temp*_input"):
                try:
                    value = float(input_path.read_text().strip())
                    value = value / 1000.0 if value > 1000 else value
                    if not 0 < value < 150:
                        continue
                    label_path = input_path.with_name(input_path.name.replace("_input", "_label"))
                    label = label_path.read_text().strip() if label_path.exists() else ""
                    sensor_name = label or input_path.name.removesuffix("_input")
                    is_cpu = any(
                        word in f"{device_name} {label}".lower()
                        for word in ("coretemp", "k10temp", "zenpower", "cpu", "package", "tctl", "tdie")
                    )
                    sensor = ThermalSensor(
                        identifier=f"hwmon:{path.name}:{input_path.name}",
                        label=f"{device_name} / {sensor_name}" if device_name else sensor_name,
                        temperature_c=value,
                        source="hwmon",
                    )
                    (preferred if is_cpu else fallback).append(sensor)
                except (OSError, ValueError):
                    continue
        sensors = preferred + fallback
        hotspot_group = preferred or fallback
        hotspot = max((sensor.temperature_c for sensor in hotspot_group), default=None)
        return hotspot, len(sensors), sensors

    def _read_temperature(self) -> float | None:
        return self._read_thermals()[0]

    def _read_gpu_percent(self, elapsed: float) -> tuple[float | None, str]:
        values: list[float] = []
        for device in self._gpu_devices:
            for path in (
                device / "gpu_busy_percent",
                device / "gt_busy_percent",
                device / "gt/gt0/busy_percent",
                device.parent / "gpu_busy_percent",
            ):
                try:
                    values.append(float(path.read_text().strip()))
                except (OSError, ValueError):
                    continue
        if values:
            return min(100.0, sum(values) / len(values)), "DRM sysfs / global engine"
        if self.gpu_driver in ("i915", "xe"):
            fdinfo_percent = self._read_drm_fdinfo_percent(elapsed)
            if fdinfo_percent is not None:
                return fdinfo_percent, "DRM fdinfo / accessible clients"
            return None, f"{self.gpu_driver} / no readable utilization counter"
        return None, "No readable DRM utilization counter"

    def _gpu_device_paths(self) -> list[Path]:
        paths: list[Path] = []
        for card in sorted((self.sys_root / "class/drm").glob("card[0-9]*")):
            device = card / "device"
            if device.exists():
                paths.append(device)
        def device_order(path: Path) -> tuple[int, str]:
            try:
                vendor = (path / "vendor").read_text().strip().lower()
            except OSError:
                vendor = ""
            return {"0x8086": 0, "0x1002": 1, "0x10de": 2}.get(vendor, 3), str(path)

        paths.sort(key=device_order)
        return paths

    def _read_gpu_identity(self) -> tuple[str, str, str, str, str]:
        if not self._gpu_devices:
            return "N/A", "", "", "N/A", "N/A"
        device = self._gpu_devices[0]
        properties: dict[str, str] = {}
        try:
            for line in (device / "uevent").read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    properties[key] = value
        except OSError:
            pass
        driver_path = device / "driver"
        try:
            driver = driver_path.resolve().name if driver_path.exists() else properties.get("DRIVER", "N/A")
        except OSError:
            driver = properties.get("DRIVER", "N/A")
        try:
            vendor = (device / "vendor").read_text().strip().lower()
        except OSError:
            vendor = ""
        try:
            device_id = (device / "device").read_text().strip().lower()
        except OSError:
            device_id = ""
        address = properties.get("PCI_SLOT_NAME", "")
        if not address:
            resolved_name = device.resolve().name
            address = resolved_name if re.fullmatch(r"[0-9a-fA-F:.]+", resolved_name) else "N/A"
        render_nodes: list[str] = []
        for gpu in self._gpu_devices:
            render_nodes.extend(path.name for path in (gpu / "drm").glob("renderD*"))
        nodes = ", ".join(f"/dev/dri/{name}" for name in sorted(set(render_nodes))) or "N/A"
        return driver, vendor, device_id, address, nodes

    def _read_gpu_name(self) -> str:
        known_intel = {
            "0x4680": "Intel UHD Graphics 770",
            "0xa780": "Intel UHD Graphics 770",
        }
        if self.gpu_vendor_id == "0x8086" and self.gpu_device_id in known_intel:
            return known_intel[self.gpu_device_id]
        vendor_names = {"0x10de": "NVIDIA GPU", "0x1002": "AMD Radeon GPU", "0x8086": "Intel Graphics"}
        for device in self._gpu_devices:
            for filename in ("product_name", "label"):
                try:
                    value = (device / filename).read_text().strip()
                    if value:
                        return value
                except OSError:
                    pass
        for database in (Path("/usr/share/misc/pci.ids"), Path("/usr/share/hwdata/pci.ids")):
            try:
                name = parse_pci_device_name(database.read_text(encoding="utf-8", errors="replace"), self.gpu_vendor_id, self.gpu_device_id)
            except OSError:
                continue
            if name:
                return name
        if self.gpu_vendor_id or self.gpu_device_id:
            return f"{vendor_names.get(self.gpu_vendor_id, 'DRM GPU')} ({self.gpu_device_id or 'unknown device'})"
        return "GPU provider unavailable"

    def _read_gpu_memory(self) -> tuple[int | None, int | None]:
        total = used = 0
        found = False
        for device in self._gpu_devices:
            try:
                total += int((device / "mem_info_vram_total").read_text().strip())
                used += int((device / "mem_info_vram_used").read_text().strip())
                found = True
            except (OSError, ValueError):
                continue
        return (total, used) if found else (None, None)

    def _read_gpu_frequency(self) -> tuple[float | None, float | None]:
        current: list[float] = []
        maximum: list[float] = []
        for device in self._gpu_devices:
            card = device.parent
            for path in (
                device / "gt_cur_freq_mhz",
                device / "gt/gt0/rps_cur_freq_mhz",
                card / "gt/gt0/rps_cur_freq_mhz",
                device / "tile0/gt0/freq0/cur_freq",
            ):
                try:
                    current.append(float(path.read_text().strip()))
                except (OSError, ValueError):
                    continue
            for path in (
                device / "gt_max_freq_mhz",
                device / "gt/gt0/rps_max_freq_mhz",
                card / "gt/gt0/rps_max_freq_mhz",
                device / "tile0/gt0/freq0/max_freq",
            ):
                try:
                    maximum.append(float(path.read_text().strip()))
                except (OSError, ValueError):
                    continue
        return (sum(current) / len(current) if current else None, max(maximum) if maximum else None)

    def _scan_gpu_fds(self) -> None:
        now = time.monotonic()
        if now - self._last_gpu_fd_scan < 5.0:
            return
        paths: list[tuple[str, str]] = []
        try:
            process_dirs = self.proc_root.iterdir()
        except OSError:
            process_dirs = []
        for process_dir in process_dirs:
            if not process_dir.name.isdigit():
                continue
            try:
                descriptors = (process_dir / "fd").iterdir()
            except OSError:
                continue
            for descriptor in descriptors:
                try:
                    target = os.readlink(descriptor)
                except OSError:
                    continue
                if target.startswith("/dev/dri/"):
                    paths.append((process_dir.name, descriptor.name))
        self._gpu_fd_paths = paths
        self._last_gpu_fd_scan = now

    def _read_drm_fdinfo_percent(self, elapsed: float) -> float | None:
        self._scan_gpu_fds()
        current: dict[tuple[str, str], int] = {}
        found = False
        for pid, descriptor in self._gpu_fd_paths:
            try:
                text = (self.proc_root / pid / "fdinfo" / descriptor).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            driver, pdev, client_id, engines = parse_drm_fdinfo(text)
            if driver not in ("i915", "xe") or not engines:
                continue
            found = True
            client = f"{pdev}:{client_id}" if client_id else f"{pid}:{descriptor}"
            for engine, counter in engines.items():
                key = (client, engine)
                current[key] = max(counter, current.get(key, 0))
        if not found:
            self._previous_gpu_counters = {}
            return None
        busy_ns = sum(
            max(0, counter - self._previous_gpu_counters.get(key, counter))
            for key, counter in current.items()
        )
        self._previous_gpu_counters = current
        return min(100.0, busy_ns / max(0.05, elapsed) / 1_000_000_000.0 * 100.0)

    @staticmethod
    def _optional_metric(value: str | None) -> float | None:
        if not value or value.strip().lower() in ("n/a", "[n/a]", "not supported", "-"):
            return None
        match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", value)
        return float(match.group(0)) if match else None

    def _query_nvidia_smi(self, fields: tuple[str, ...]) -> list[dict[str, str]]:
        if not self._nvidia_smi_path:
            return []
        command = [
            self._nvidia_smi_path,
            f"--query-gpu={','.join(fields)}",
            "--format=csv,noheader,nounits",
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=1.5, check=False)
        except (OSError, subprocess.SubprocessError):
            return []
        return parse_nvidia_smi_csv(result.stdout, fields) if result.returncode == 0 else []

    def _read_nvidia_gpus(self) -> list[GpuSnapshot]:
        fields = NVIDIA_QUERY_FIELDS
        rows = self._query_nvidia_smi(fields)
        if not rows:
            fields = NVIDIA_FALLBACK_FIELDS
            rows = self._query_nvidia_smi(fields)
        gpus: list[GpuSnapshot] = []
        for row in rows:
            index = row.get("index", "?")
            raw_address = row.get("pci.bus_id", "N/A")
            address_match = re.search(r"([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7])$", raw_address)
            address = address_match.group(1).lower() if address_match else raw_address
            memory_used_mb = self._optional_metric(row.get("memory.used"))
            memory_total_mb = self._optional_metric(row.get("memory.total"))
            gpus.append(
                GpuSnapshot(
                    identifier=f"nvidia:{index}:{address}",
                    name=row.get("name", "NVIDIA GPU"),
                    utilization=self._optional_metric(row.get("utilization.gpu")),
                    utilization_source="nvidia-smi / global device",
                    driver=f"nvidia {row.get('driver_version', '').strip()}".strip(),
                    pci_id=row.get("pci.device_id", "N/A"),
                    pci_address=address,
                    device_nodes=f"/dev/nvidia{index}",
                    frequency_mhz=self._optional_metric(row.get("clocks.gr")),
                    frequency_max_mhz=self._optional_metric(row.get("clocks.max.graphics")),
                    memory_mode="Dedicated VRAM",
                    memory_total=int(memory_total_mb * 1024 * 1024) if memory_total_mb is not None else None,
                    memory_used=int(memory_used_mb * 1024 * 1024) if memory_used_mb is not None else None,
                    temperature_c=self._optional_metric(row.get("temperature.gpu")),
                    power_watts=self._optional_metric(row.get("power.draw")),
                    fan_percent=self._optional_metric(row.get("fan.speed")),
                )
            )
        return gpus

    def _read_npu_name(self) -> str | None:
        accel_root = self.sys_root / "class/accel"
        devices = list(accel_root.glob("accel*")) if accel_root.exists() else []
        if not devices:
            return None
        names: list[str] = []
        for device in devices:
            try:
                names.append((device / "device/uevent").read_text().splitlines()[0])
            except (OSError, IndexError):
                names.append(device.name)
        return ", ".join(names)

    def _read_power(self) -> tuple[float | None, str, float | None]:
        values: list[float] = []
        statuses: list[str] = []
        capacities: list[float] = []
        for battery in (self.sys_root / "class/power_supply").glob("BAT*"):
            try:
                values.append(float((battery / "power_now").read_text().strip()) / 1_000_000.0)
            except (OSError, ValueError):
                try:
                    current = float((battery / "current_now").read_text().strip()) / 1_000_000.0
                    voltage = float((battery / "voltage_now").read_text().strip()) / 1_000_000.0
                    values.append(current * voltage)
                except (OSError, ValueError):
                    pass
            try:
                statuses.append((battery / "status").read_text().strip())
            except OSError:
                pass
            try:
                capacities.append(float((battery / "capacity").read_text().strip()))
            except (OSError, ValueError):
                pass
        status = ", ".join(sorted(set(statuses))) if statuses else "AC power / no battery telemetry"
        capacity = sum(capacities) / len(capacities) if capacities else None
        return (sum(values) if values else None, status, capacity)

    def _read_cpu_package_power(self, elapsed: float) -> float | None:
        current: dict[str, int] = {}
        watts: list[float] = []
        powercap_root = self.sys_root / "class/powercap"
        for energy_path in powercap_root.glob("intel-rapl:*/energy_uj"):
            key = str(energy_path)
            try:
                energy = int(energy_path.read_text().strip())
            except (OSError, ValueError):
                continue
            current[key] = energy
            previous = self._previous_rapl_energy.get(key)
            if previous is None:
                continue
            delta = energy - previous
            if delta < 0:
                try:
                    maximum = int((energy_path.parent / "max_energy_range_uj").read_text().strip())
                    delta = energy + maximum - previous
                except (OSError, ValueError):
                    continue
            watts.append(delta / 1_000_000.0 / max(0.05, elapsed))
        self._previous_rapl_energy = current
        return sum(watts) if watts else None

    def _read_memory_pressure(self) -> float:
        text = self._read("pressure/memory")
        match = re.search(r"^some\s+avg10=([0-9.]+)", text, re.MULTILINE)
        return float(match.group(1)) if match else 0.0

    def _read_disk_space(self) -> tuple[int, int, int]:
        try:
            values = os.statvfs("/")
            capacity = values.f_blocks * values.f_frsize
            free = values.f_bavail * values.f_frsize
            return capacity, max(0, capacity - free), free
        except OSError:
            return 0, 0, 0

    def _read_disk_identity(self, device: str) -> tuple[str, str, int]:
        path = self.sys_root / "block" / device
        try:
            model = (path / "device/model").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            model = ""
        model = re.sub(r"\s+", " ", model) or f"/dev/{device}"

        try:
            capacity = int((path / "size").read_text().strip()) * 512
        except (OSError, ValueError):
            capacity = 0

        try:
            rotational = int((path / "queue/rotational").read_text().strip())
        except (OSError, ValueError):
            rotational = -1
        try:
            virtual = "virtual" in path.resolve().parts
        except OSError:
            virtual = False

        if device.startswith("nvme"):
            device_type = "NVMe"
        elif device.startswith("mmcblk"):
            device_type = "eMMC / SD"
        elif virtual:
            device_type = "Virtual disk"
        elif rotational == 1:
            device_type = "HDD"
        elif rotational == 0:
            device_type = "SSD"
        else:
            device_type = "Block device"
        return model, device_type, capacity

    def _read_disk_snapshots(
        self,
        counters: dict[str, tuple[int, int, int]],
        elapsed: float,
    ) -> list[DiskSnapshot]:
        previous_counters = getattr(self, "_previous_disks", {})
        snapshots: list[DiskSnapshot] = []
        for device in sorted(self._physical_devices):
            read_total, write_total, io_ms = counters.get(device, (0, 0, 0))
            previous = previous_counters.get(device)
            if previous is None:
                read_bps = write_bps = busy_percent = 0.0
            else:
                read_bps = max(0, read_total - previous[0]) / elapsed
                write_bps = max(0, write_total - previous[1]) / elapsed
                busy_percent = min(100.0, 100.0 * max(0, io_ms - previous[2]) / (elapsed * 1000.0))
            model, device_type, capacity = self._read_disk_identity(device)
            snapshots.append(
                DiskSnapshot(
                    identifier=device,
                    model=model,
                    device_type=device_type,
                    busy_percent=busy_percent,
                    read_bps=read_bps,
                    write_bps=write_bps,
                    read_total=read_total,
                    write_total=write_total,
                    capacity=capacity,
                )
            )
        self._previous_disks = counters
        return snapshots

    def _read_network_speed(self, interface: str) -> int | None:
        try:
            speed = int((self.sys_root / "class/net" / interface / "speed").read_text().strip())
            return speed if speed > 0 else None
        except (OSError, ValueError):
            return None

    def _read_network_snapshots(
        self,
        counters: dict[str, tuple[int, int]],
        elapsed: float,
    ) -> list[NetworkInterfaceSnapshot]:
        previous_counters = getattr(self, "_previous_networks", {})
        default_interface = parse_default_route_interface(self._read("net/route"))
        try:
            sysfs_names = {
                path.name for path in (self.sys_root / "class/net").iterdir() if path.name != "lo"
            }
        except OSError:
            sysfs_names = set()
        interface_names = sysfs_names | set(counters)
        snapshots: list[NetworkInterfaceSnapshot] = []
        for interface in interface_names:
            receive_total, send_total = counters.get(interface, (0, 0))
            previous = previous_counters.get(interface)
            if previous is None:
                receive_bps = send_bps = 0.0
            else:
                receive_bps = max(0, receive_total - previous[0]) / elapsed
                send_bps = max(0, send_total - previous[1]) / elapsed
            (
                connection_type,
                hardware_address,
                ipv4_addresses,
                ipv6_addresses,
                mtu,
                state,
            ) = self._read_network_identity(interface)
            snapshots.append(
                NetworkInterfaceSnapshot(
                    identifier=interface,
                    connection_type=connection_type,
                    state=state,
                    link_speed_mbps=self._read_network_speed(interface),
                    receive_bps=receive_bps,
                    send_bps=send_bps,
                    receive_total=receive_total,
                    send_total=send_total,
                    hardware_address=hardware_address,
                    ipv4_addresses=ipv4_addresses,
                    ipv6_addresses=ipv6_addresses,
                    mtu=mtu,
                    primary=interface == default_interface,
                )
            )

        active_states = {"Up", "Unknown"}
        type_order = {"Ethernet": 0, "Wi-Fi": 1, "Bridge": 2, "Tunnel": 3, "Virtual Ethernet": 4}
        snapshots.sort(
            key=lambda item: (
                not item.primary,
                item.state not in active_states,
                type_order.get(item.connection_type, 5),
                item.identifier,
            )
        )
        if snapshots and not any(item.primary and item.state in active_states for item in snapshots):
            for item in snapshots:
                item.primary = False
            primary = next((item for item in snapshots if item.state in active_states), snapshots[0])
            primary.primary = True
            snapshots.sort(key=lambda item: (not item.primary, item.identifier))
        self._previous_networks = counters
        return snapshots

    def _read_network_details(self) -> tuple[int, str, int | None]:
        interfaces: list[Path] = []
        net_root = self.sys_root / "class/net"
        for path in sorted(net_root.glob("*")):
            if path.name == "lo":
                continue
            interfaces.append(path)
        primary = "No active interface"
        speed: int | None = None
        default_interface = parse_default_route_interface(self._read("net/route"))
        ordered = sorted(interfaces, key=lambda path: (path.name != default_interface, path.name))
        for path in ordered:
            try:
                active = (path / "operstate").read_text().strip() in ("up", "unknown")
            except OSError:
                active = False
            if not active:
                continue
            primary = path.name
            try:
                raw_speed = int((path / "speed").read_text().strip())
                speed = raw_speed if raw_speed > 0 else None
            except (OSError, ValueError):
                speed = None
            break
        return len(interfaces), primary, speed

    def _read_network_identity(self, interface: str) -> tuple[str, str, str, str, int | None, str]:
        path = self.sys_root / "class/net" / interface
        if not path.exists():
            return "N/A", "N/A", "N/A", "N/A", None, "Unavailable"
        name = interface.lower()
        if (path / "wireless").exists() or name.startswith("wl"):
            connection_type = "Wi-Fi"
        elif (path / "bridge").exists() or name.startswith(("br", "virbr")):
            connection_type = "Bridge"
        elif name.startswith(("tun", "tap", "wg")):
            connection_type = "Tunnel"
        elif name.startswith(("docker", "veth")):
            connection_type = "Virtual Ethernet"
        elif (path / "device").exists() or name.startswith(("en", "eth")):
            connection_type = "Ethernet"
        else:
            connection_type = "Virtual / other"
        try:
            hardware_address = (path / "address").read_text().strip()
        except OSError:
            hardware_address = "N/A"
        try:
            mtu = int((path / "mtu").read_text().strip())
        except (OSError, ValueError):
            mtu = None
        try:
            state = (path / "operstate").read_text().strip().title()
        except OSError:
            state = "Unknown"

        ipv4 = "N/A"
        if fcntl is not None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                request = struct.pack("256s", interface[:15].encode("utf-8"))
                ipv4 = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), 0x8915, request)[20:24])
            except OSError:
                pass
            finally:
                sock.close()

        ipv6_values: list[str] = []
        for line in self._read("net/if_inet6").splitlines():
            fields = line.split()
            if len(fields) != 6 or fields[5] != interface:
                continue
            try:
                ipv6_values.append(str(ipaddress.IPv6Address(int(fields[0], 16))))
            except ValueError:
                continue
        return connection_type, hardware_address, ipv4, ", ".join(ipv6_values) or "N/A", mtu, state

    def _read_file_handles(self) -> int:
        try:
            return int(self._read("sys/fs/file-nr", "0").split()[0])
        except (ValueError, IndexError):
            return 0

    def _read_process_io(self, process_dir: Path) -> tuple[int, int]:
        values: dict[str, int] = {}
        try:
            for line in (process_dir / "io").read_text().splitlines():
                if ":" in line:
                    key, raw = line.split(":", 1)
                    values[key] = int(raw.strip())
        except (OSError, ValueError):
            pass
        return values.get("read_bytes", 0), values.get("write_bytes", 0)

    def _read_process_identity(self, process_dir: Path) -> tuple[str, int]:
        user = "?"
        swap_bytes = 0
        try:
            status = (process_dir / "status").read_text(encoding="utf-8", errors="replace")
            match = re.search(r"^Uid:\s+(\d+)", status, re.MULTILINE)
            if match:
                uid = int(match.group(1))
                if pwd is not None:
                    try:
                        user = pwd.getpwuid(uid).pw_name
                    except KeyError:
                        user = str(uid)
                else:
                    user = str(uid)
            swap_match = re.search(r"^VmSwap:\s+(\d+)\s+kB", status, re.MULTILINE)
            if swap_match:
                swap_bytes = int(swap_match.group(1)) * 1024
        except OSError:
            pass
        return user, swap_bytes

    @staticmethod
    def _read_process_control_group(process_dir: Path) -> str:
        try:
            groups = []
            for line in (process_dir / "cgroup").read_text(encoding="utf-8", errors="replace").splitlines():
                fields = line.split(":", 2)
                if len(fields) == 3 and fields[2]:
                    groups.append(fields[2])
            return groups[0] if groups else "/"
        except OSError:
            return "/"

    def _read_processes(self, elapsed: float) -> list[ProcessInfo]:
        processes: list[ProcessInfo] = []
        current_ticks: dict[int, int] = {}
        try:
            process_dirs: Iterable[Path] = self.proc_root.iterdir()
        except OSError:
            return processes
        boot_time = time.time() - self._read_uptime()
        for process_dir in process_dirs:
            if not process_dir.name.isdigit():
                continue
            try:
                parsed = parse_process_stat((process_dir / "stat").read_text(encoding="utf-8", errors="replace"))
                pid = int(parsed["pid"])
                ticks = int(parsed["cpu_ticks"])
                current_ticks[pid] = ticks
                previous = self._previous_process_ticks.get(pid, ticks)
                cpu = max(0.0, (ticks - previous) / self.clock_ticks / elapsed * 100.0 / self.cpu_count)
                try:
                    command_parts = (process_dir / "cmdline").read_bytes().split(b"\0")
                    command = " ".join(part.decode("utf-8", "replace") for part in command_parts if part)
                except OSError:
                    command = ""
                read_bytes, write_bytes = self._read_process_io(process_dir)
                process_user, swap_bytes = self._read_process_identity(process_dir)
                processes.append(
                    ProcessInfo(
                        pid=pid,
                        ppid=int(parsed["ppid"]),
                        name=str(parsed["name"]),
                        command=command or f"[{parsed['name']}]",
                        user=process_user,
                        state=STATE_NAMES.get(str(parsed["state"]), str(parsed["state"])),
                        cpu_percent=min(cpu, 100.0),
                        memory_bytes=max(0, int(parsed["rss_pages"]) * self.page_size),
                        threads=max(0, int(parsed["threads"])),
                        read_bytes=read_bytes,
                        write_bytes=write_bytes,
                        started_at=boot_time + int(parsed["start_ticks"]) / self.clock_ticks,
                        swap_bytes=swap_bytes,
                        user_cpu_seconds=int(parsed["user_ticks"]) / self.clock_ticks,
                        system_cpu_seconds=int(parsed["system_ticks"]) / self.clock_ticks,
                        control_group=self._read_process_control_group(process_dir),
                    )
                )
            except (OSError, PermissionError, ProcessLookupError, ValueError, IndexError):
                continue
        self._previous_process_ticks = current_ticks
        return processes

    def _read_uptime(self) -> float:
        try:
            return float(self._read("uptime", "0").split()[0])
        except (ValueError, IndexError):
            return 0.0

    def collect(self) -> SystemSnapshot:
        now = time.monotonic()
        elapsed = max(0.05, now - self._previous_time) if self._previous_time is not None else 1.0

        cpu_stats = parse_cpu_stat(self._read("stat"))
        overall = kernel = 0.0
        per_cpu: list[float] = []
        for name, values in cpu_stats.items():
            previous = self._previous_cpu.get(name, values)
            usage, kernel_usage = cpu_percent(previous, values)
            if name == "cpu":
                overall, kernel = usage, kernel_usage
            else:
                per_cpu.append(usage)
        self._previous_cpu = cpu_stats
        stat_text = self._read("stat")
        context_match = re.search(r"^ctxt\s+(\d+)", stat_text, re.MULTILINE)
        interrupt_match = re.search(r"^intr\s+(\d+)", stat_text, re.MULTILINE)

        memory = parse_meminfo(self._read("meminfo"))
        memory_total = memory.get("MemTotal", 0)
        memory_available = memory.get("MemAvailable", memory.get("MemFree", 0))
        memory_used = max(0, memory_total - memory_available)
        memory_cached = memory.get("Cached", 0) + memory.get("SReclaimable", 0)
        swap_total = memory.get("SwapTotal", 0)
        swap_used = max(0, swap_total - memory.get("SwapFree", 0))

        self._physical_devices = self._find_physical_devices()
        disk_counters = parse_diskstats_by_device(self._read("diskstats"), self._physical_devices)
        disks = self._read_disk_snapshots(disk_counters, elapsed)
        disk = (
            sum(item.read_total for item in disks),
            sum(item.write_total for item in disks),
            sum(disk_counters.get(item.identifier, (0, 0, 0))[2] for item in disks),
        )
        disk_read = sum(item.read_bps for item in disks)
        disk_write = sum(item.write_bps for item in disks)
        disk_busy = sum(item.busy_percent for item in disks) / len(disks) if disks else 0.0
        root_capacity, disk_used, disk_free = self._read_disk_space()
        disk_capacity = sum(item.capacity for item in disks) or root_capacity

        network_counters = parse_netdev_interfaces(self._read("net/dev"))
        network_interfaces = self._read_network_snapshots(network_counters, elapsed)
        network = (
            sum(item.receive_total for item in network_interfaces),
            sum(item.send_total for item in network_interfaces),
        )
        network_receive = sum(item.receive_bps for item in network_interfaces)
        network_send = sum(item.send_bps for item in network_interfaces)
        primary_network = next((item for item in network_interfaces if item.primary), None)
        interface_count = len(network_interfaces)
        primary_interface = primary_network.identifier if primary_network else "No active interface"
        link_speed = primary_network.link_speed_mbps if primary_network else None
        network_connection_type = primary_network.connection_type if primary_network else "N/A"
        network_hardware_address = primary_network.hardware_address if primary_network else "N/A"
        network_ipv4_addresses = primary_network.ipv4_addresses if primary_network else "N/A"
        network_ipv6_addresses = primary_network.ipv6_addresses if primary_network else "N/A"
        network_mtu = primary_network.mtu if primary_network else None
        network_state = primary_network.state if primary_network else "Unavailable"

        processes = self._read_processes(elapsed)
        try:
            load_average = tuple(float(value) for value in self._read("loadavg", "0 0 0").split()[:3])
        except ValueError:
            load_average = (0.0, 0.0, 0.0)

        temperature, thermal_sensor_count, thermal_sensors = self._read_thermals()
        gpu_memory_total, gpu_memory_used = self._read_gpu_memory()
        gpu_frequency, gpu_frequency_max = self._read_gpu_frequency()
        gpu_percent, gpu_utilization_source = self._read_gpu_percent(elapsed)
        nvidia_gpus = self._read_nvidia_gpus()
        gpus: list[GpuSnapshot] = []
        primary_is_nvidia = self.gpu_vendor_id == "0x10de"
        if self.gpu_name != "GPU provider unavailable" and not (primary_is_nvidia and nvidia_gpus):
            gpus.append(
                GpuSnapshot(
                    identifier=f"drm:{self.gpu_pci_address}:{self.gpu_pci_id}",
                    name=self.gpu_name,
                    utilization=gpu_percent,
                    utilization_source=gpu_utilization_source,
                    driver=self.gpu_driver,
                    pci_id=self.gpu_pci_id,
                    pci_address=self.gpu_pci_address,
                    device_nodes=self.gpu_render_nodes,
                    frequency_mhz=gpu_frequency,
                    frequency_max_mhz=gpu_frequency_max,
                    memory_mode="Dedicated VRAM" if gpu_memory_total else self.gpu_memory_mode,
                    memory_total=gpu_memory_total,
                    memory_used=gpu_memory_used,
                )
            )
        gpus.extend(nvidia_gpus)
        power_watts, battery_status, battery_percent = self._read_power()
        for gpu in gpus:
            if gpu.temperature_c is not None:
                thermal_sensors.append(
                    ThermalSensor(
                        identifier=f"gpu:{gpu.identifier}",
                        label=f"{gpu.name} / GPU",
                        temperature_c=gpu.temperature_c,
                        source=gpu.utilization_source.split(" / ", 1)[0],
                    )
                )
        thermal_sensor_count = len(thermal_sensors)
        cpu_package_watts = self._read_cpu_package_power(elapsed)
        gpu_power_values = [gpu.power_watts for gpu in gpus if gpu.power_watts is not None]
        gpu_power_watts = sum(gpu_power_values) if gpu_power_values else None
        if power_watts is not None:
            observed_power_watts = power_watts
            power_source = "System input / battery telemetry"
        else:
            components = [value for value in (cpu_package_watts, gpu_power_watts) if value is not None]
            observed_power_watts = sum(components) if components else None
            source_names = []
            if cpu_package_watts is not None:
                source_names.append("CPU package")
            if gpu_power_watts is not None:
                source_names.append("GPU device")
            power_source = " + ".join(source_names) if source_names else "No readable power counter"

        self._previous_time = now
        return SystemSnapshot(
            timestamp=time.time(),
            cpu_percent=overall,
            per_cpu_percent=per_cpu,
            kernel_percent=kernel,
            cpu_mhz=self._read_cpu_frequency(),
            cpu_max_mhz=self.cpu_max_mhz,
            cpu_model=self.cpu_model,
            cpu_physical_cores=self.cpu_physical_cores,
            cpu_core_types=self.cpu_core_types,
            cpu_cache_summary=self.cpu_cache_summary,
            context_switches=int(context_match.group(1)) if context_match else 0,
            interrupts=int(interrupt_match.group(1)) if interrupt_match else 0,
            memory_total=memory_total,
            memory_used=memory_used,
            memory_available=memory_available,
            memory_cached=memory_cached,
            memory_active=memory.get("Active", 0),
            memory_inactive=memory.get("Inactive", 0),
            memory_buffers=memory.get("Buffers", 0),
            memory_slab=memory.get("Slab", 0),
            memory_committed=memory.get("Committed_AS", 0),
            memory_shared=memory.get("Shmem", 0),
            memory_pressure_percent=self._read_memory_pressure(),
            swap_total=swap_total,
            swap_used=swap_used,
            disk_read_bps=disk_read,
            disk_write_bps=disk_write,
            disk_busy_percent=disk_busy,
            disk_read_total=disk[0],
            disk_write_total=disk[1],
            disk_device_count=len(self._physical_devices),
            disk_capacity=disk_capacity,
            disk_used=disk_used,
            disk_free=disk_free,
            disks=disks,
            network_receive_bps=network_receive,
            network_send_bps=network_send,
            network_receive_total=network[0],
            network_send_total=network[1],
            network_interface_count=interface_count,
            primary_interface=primary_interface,
            link_speed_mbps=link_speed,
            network_connection_type=network_connection_type,
            network_hardware_address=network_hardware_address,
            network_ipv4_addresses=network_ipv4_addresses,
            network_ipv6_addresses=network_ipv6_addresses,
            network_mtu=network_mtu,
            network_state=network_state,
            network_interfaces=network_interfaces,
            temperature_c=temperature,
            thermal_sensor_count=thermal_sensor_count,
            thermal_sensors=thermal_sensors,
            gpu_percent=gpu_percent,
            gpu_name=self.gpu_name,
            gpu_memory_total=gpu_memory_total,
            gpu_memory_used=gpu_memory_used,
            gpu_driver=self.gpu_driver,
            gpu_pci_id=self.gpu_pci_id,
            gpu_pci_address=self.gpu_pci_address,
            gpu_render_nodes=self.gpu_render_nodes,
            gpu_frequency_mhz=gpu_frequency,
            gpu_frequency_max_mhz=gpu_frequency_max,
            gpu_memory_mode="Dedicated VRAM" if gpu_memory_total else self.gpu_memory_mode,
            gpu_utilization_source=gpu_utilization_source,
            gpus=gpus,
            npu_name=self.npu_name,
            power_watts=power_watts,
            cpu_package_watts=cpu_package_watts,
            gpu_power_watts=gpu_power_watts,
            observed_power_watts=observed_power_watts,
            power_source=power_source,
            battery_status=battery_status,
            battery_percent=battery_percent,
            uptime_seconds=self._read_uptime(),
            process_count=len(processes),
            thread_count=sum(process.threads for process in processes),
            file_handle_count=self._read_file_handles(),
            load_average=(load_average + (0.0, 0.0, 0.0))[:3],
            processes=processes,
        )

    @staticmethod
    def terminate_process(pid: int, force: bool = False) -> None:
        LinuxMetricsCollector._signal_process(pid, signal.SIGKILL if force else signal.SIGTERM)

    @staticmethod
    def suspend_process(pid: int) -> None:
        LinuxMetricsCollector._signal_process(pid, signal.SIGSTOP)

    @staticmethod
    def resume_process(pid: int) -> None:
        LinuxMetricsCollector._signal_process(pid, signal.SIGCONT)

    @staticmethod
    def _signal_process(pid: int, process_signal: signal.Signals) -> None:
        if pid in (0, 1, os.getpid()):
            raise PermissionError("This process is protected by TMOG Linux.")
        os.kill(pid, process_signal)

    def system_information(self) -> list[tuple[str, str]]:
        release: dict[str, str] = {}
        try:
            for line in Path("/etc/os-release").read_text().splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    release[key] = value.strip().strip('"')
        except OSError:
            pass
        graphics: list[str] = []
        if self.gpu_name != "GPU provider unavailable" and self.gpu_vendor_id != "0x10de":
            graphics.append(f"{self.gpu_name} ({self.gpu_driver}, {self.gpu_pci_address})")
        graphics.extend(f"{gpu.name} ({gpu.driver}, {gpu.pci_address})" for gpu in self._read_nvidia_gpus())
        if not graphics and self.gpu_name != "GPU provider unavailable":
            graphics.append(f"{self.gpu_name} ({self.gpu_driver}, {self.gpu_pci_address})")
        return [
            ("Operating system", release.get("PRETTY_NAME", platform.platform())),
            ("Kernel", platform.release()),
            ("Host name", socket.gethostname()),
            ("Architecture", platform.machine()),
            ("Processor", self.cpu_model),
            ("Physical cores", str(self.cpu_physical_cores)),
            ("Logical processors", str(self.cpu_count)),
            ("CPU caches", self.cpu_cache_summary),
            ("Graphics", "  •  ".join(graphics) or "GPU provider unavailable"),
            ("Python", platform.python_version()),
        ]

    @staticmethod
    def _desktop_file(path: Path) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            parser.read_file(stream)
        return parser

    @staticmethod
    def _xdg_autostart_locations() -> tuple[Path, list[Path]]:
        user_root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        system_value = os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg")
        system_roots = [Path(value) for value in system_value.split(os.pathsep) if value]
        return user_root / "autostart", [root / "autostart" for root in system_roots]

    @classmethod
    def startup_entries(cls) -> list[StartupEntry]:
        user_directory, system_directories = cls._xdg_autostart_locations()
        system_paths: dict[str, Path] = {}
        for directory in system_directories:
            for path in sorted(directory.glob("*.desktop")):
                system_paths.setdefault(path.name, path)

        candidates: dict[str, tuple[Path, str]] = {
            name: (path, "System") for name, path in system_paths.items()
        }
        for path in sorted(user_directory.glob("*.desktop")):
            source = "User override" if path.name in system_paths else "User"
            candidates[path.name] = (path, source)

        entries: list[StartupEntry] = []
        for path, source in candidates.values():
            try:
                parser = cls._desktop_file(path)
                values = parser["Desktop Entry"]
            except (OSError, KeyError, configparser.Error):
                continue
            if values.get("Type", "Application") != "Application":
                continue
            hidden = values.get("Hidden", "false").strip().lower() == "true"
            desktop_enabled = (
                values.get("X-GNOME-Autostart-enabled", "true").strip().lower() != "false"
            )
            entries.append(
                StartupEntry(
                    name=values.get("Name", path.stem),
                    command=values.get("Exec", ""),
                    source=source,
                    enabled=not hidden and desktop_enabled,
                    desktop_file=path,
                )
            )
        return sorted(entries, key=lambda entry: entry.name.casefold())

    @classmethod
    def set_startup_enabled(cls, entry: StartupEntry, enabled: bool) -> Path:
        source = entry.desktop_file
        if not source.is_file():
            raise FileNotFoundError(f"Startup entry no longer exists: {source}")

        user_directory, _system_directories = cls._xdg_autostart_locations()
        if entry.source == "System":
            user_directory.mkdir(parents=True, exist_ok=True)
            target = user_directory / source.name
            shutil.copyfile(source, target)
        else:
            target = source

        parser = cls._desktop_file(target)
        if not parser.has_section("Desktop Entry"):
            raise ValueError(f"Invalid desktop entry: {target}")
        parser.set("Desktop Entry", "Hidden", str(not enabled).lower())
        parser.set("Desktop Entry", "X-GNOME-Autostart-enabled", str(enabled).lower())

        temporary = target.with_name(f".{target.name}.tmog.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                parser.write(stream, space_around_delimiters=False)
            temporary.chmod(0o644)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    @staticmethod
    def services() -> list[ServiceInfo]:
        command = [
            "systemctl",
            "list-units",
            "--type=service",
            "--all",
            "--no-legend",
            "--no-pager",
            "--plain",
        ]
        try:
            output = subprocess.run(command, capture_output=True, text=True, timeout=6, check=False).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        services: list[ServiceInfo] = []
        for line in output.splitlines():
            parts = line.strip().split(None, 4)
            if len(parts) >= 5:
                services.append(ServiceInfo(parts[0], parts[2], parts[3], parts[4]))
        return services
