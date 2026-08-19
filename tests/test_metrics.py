import unittest
import signal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch

from tmog_linux.metrics import (
    LinuxMetricsCollector,
    cpu_percent,
    format_bytes,
    parse_cpu_stat,
    parse_diskstats,
    parse_default_route_interface,
    parse_drm_fdinfo,
    parse_meminfo,
    parse_netdev,
    parse_nvidia_smi_csv,
    parse_pci_device_name,
    parse_process_stat,
)


class ParserTests(unittest.TestCase):
    def test_cpu_stat_and_percent(self):
        previous = parse_cpu_stat("cpu  100 0 50 850 0 0 0 0\ncpu0 50 0 25 425 0 0 0 0\n")
        current = parse_cpu_stat("cpu  120 0 60 870 0 0 0 0\ncpu0 60 0 30 435 0 0 0 0\n")
        usage, kernel = cpu_percent(previous["cpu"], current["cpu"])
        self.assertAlmostEqual(usage, 60.0)
        self.assertAlmostEqual(kernel, 20.0)

    def test_meminfo_uses_bytes(self):
        values = parse_meminfo("MemTotal: 1024 kB\nMemAvailable: 256 kB\n")
        self.assertEqual(values["MemTotal"], 1024 * 1024)
        self.assertEqual(values["MemAvailable"], 256 * 1024)

    def test_diskstats_filters_devices(self):
        text = "8 0 sda 1 0 10 0 2 0 20 0 0 30 0\n7 0 loop0 1 0 99 0 2 0 99 0 0 99 0\n"
        self.assertEqual(parse_diskstats(text, {"sda"}), (5120, 10240, 30))

    def test_netdev_excludes_loopback(self):
        text = "Inter-| Receive | Transmit\n face |bytes |bytes\n lo: 100 0 0 0 0 0 0 0 200 0\n eth0: 300 0 0 0 0 0 0 0 400 0\n"
        self.assertEqual(parse_netdev(text), (300, 400))

    def test_default_route_prefers_lowest_metric(self):
        text = (
            "Iface Destination Gateway Flags RefCnt Use Metric Mask\n"
            "docker0 00000000 00000000 0001 0 0 100 00000000\n"
            "eth0 00000000 0100000A 0003 0 0 10 00000000\n"
        )
        self.assertEqual(parse_default_route_interface(text), "eth0")

    def test_pci_database_lookup(self):
        text = "8086  Intel Corporation\n\t4680  Alder Lake-S GT1 [UHD Graphics 770]\n\t\t1234  Subsystem\n"
        self.assertEqual(
            parse_pci_device_name(text, "0x8086", "0x4680"),
            "Intel Corporation Alder Lake-S GT1 [UHD Graphics 770]",
        )

    def test_drm_fdinfo_engine_counters(self):
        driver, pdev, client_id, engines = parse_drm_fdinfo(
            "drm-driver:\ti915\ndrm-pdev:\t0000:00:02.0\ndrm-client-id:\t7\n"
            "drm-engine-render:\t123000 ns\ndrm-engine-copy:\t45000 ns\n"
        )
        self.assertEqual((driver, pdev, client_id), ("i915", "0000:00:02.0", "7"))
        self.assertEqual(engines, {"render": 123000, "copy": 45000})

    def test_nvidia_smi_csv_preserves_adapter_fields(self):
        fields = ("index", "name", "utilization.gpu", "memory.used")
        rows = parse_nvidia_smi_csv("0, NVIDIA GeForce RTX 4070, 37, 2048\n", fields)
        self.assertEqual(
            rows,
            [{"index": "0", "name": "NVIDIA GeForce RTX 4070", "utilization.gpu": "37", "memory.used": "2048"}],
        )

    def test_process_stat_handles_spaces_in_name(self):
        fields = ["S", "1"] + ["0"] * 9 + ["10", "5"] + ["0"] * 4 + ["7", "0", "100", "0", "20"]
        parsed = parse_process_stat(f"42 (name with space) {' '.join(fields)}")
        self.assertEqual(parsed["pid"], 42)
        self.assertEqual(parsed["name"], "name with space")
        self.assertEqual(parsed["user_ticks"], 10)
        self.assertEqual(parsed["system_ticks"], 5)
        self.assertEqual(parsed["cpu_ticks"], 15)
        self.assertEqual(parsed["threads"], 7)
        self.assertEqual(parsed["start_ticks"], 100)
        self.assertEqual(parsed["rss_pages"], 20)

    def test_byte_formatting(self):
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1024 * 1024, rate=True), "1.0 MB/s")

    def test_process_control_signals_and_protected_pids(self):
        with patch("tmog_linux.metrics.os.kill") as kill:
            LinuxMetricsCollector.terminate_process(4242)
            LinuxMetricsCollector.terminate_process(4242, force=True)
            LinuxMetricsCollector.suspend_process(4242)
            LinuxMetricsCollector.resume_process(4242)
            self.assertEqual(
                kill.call_args_list,
                [
                    call(4242, signal.SIGTERM),
                    call(4242, signal.SIGKILL),
                    call(4242, signal.SIGSTOP),
                    call(4242, signal.SIGCONT),
                ],
            )

        with self.assertRaises(PermissionError):
            LinuxMetricsCollector.suspend_process(1)

    def test_process_identity_swap_and_control_group(self):
        with TemporaryDirectory() as directory:
            process_dir = Path(directory) / "4242"
            process_dir.mkdir()
            (process_dir / "status").write_text(
                "Name:\ttest\nUid:\t999999\t999999\t999999\t999999\nVmSwap:\t2048 kB\n"
            )
            (process_dir / "cgroup").write_text("0::/user.slice/user-1000.slice/app.scope\n")
            collector = object.__new__(LinuxMetricsCollector)

            user, swap_bytes = collector._read_process_identity(process_dir)

            self.assertEqual(user, "999999")
            self.assertEqual(swap_bytes, 2 * 1024 * 1024)
            self.assertEqual(
                collector._read_process_control_group(process_dir),
                "/user.slice/user-1000.slice/app.scope",
            )

    def test_thermal_reader_preserves_individual_hwmon_sensors(self):
        with TemporaryDirectory() as directory:
            sys_root = Path(directory)
            hwmon = sys_root / "class/hwmon/hwmon0"
            hwmon.mkdir(parents=True)
            (hwmon / "name").write_text("coretemp")
            (hwmon / "temp1_input").write_text("54000")
            (hwmon / "temp1_label").write_text("Package id 0")
            (hwmon / "temp2_input").write_text("49000")
            (hwmon / "temp2_label").write_text("Core 0")
            collector = object.__new__(LinuxMetricsCollector)
            collector.sys_root = sys_root

            hotspot, count, sensors = collector._read_thermals()

            self.assertEqual(hotspot, 54.0)
            self.assertEqual(count, 2)
            self.assertEqual(
                {sensor.label for sensor in sensors},
                {"coretemp / Package id 0", "coretemp / Core 0"},
            )

    def test_rapl_energy_delta_becomes_package_watts(self):
        with TemporaryDirectory() as directory:
            sys_root = Path(directory)
            rapl = sys_root / "class/powercap/intel-rapl:0"
            rapl.mkdir(parents=True)
            energy = rapl / "energy_uj"
            energy.write_text("1000000")
            collector = object.__new__(LinuxMetricsCollector)
            collector.sys_root = sys_root
            collector._previous_rapl_energy = {}

            self.assertIsNone(collector._read_cpu_package_power(1.0))
            energy.write_text("1350000")
            self.assertAlmostEqual(collector._read_cpu_package_power(0.5), 0.7)

    def test_network_identity_reads_sysfs_and_ipv6(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sys_root = root / "sys"
            proc_root = root / "proc"
            interface = sys_root / "class/net/en-test0"
            interface.mkdir(parents=True)
            (interface / "device").mkdir()
            (interface / "address").write_text("00:11:22:33:44:55")
            (interface / "mtu").write_text("1500")
            (interface / "operstate").write_text("up")
            (proc_root / "net").mkdir(parents=True)
            (proc_root / "net/if_inet6").write_text(
                "fe80000000000000021122fffe334455 02 40 20 80 en-test0\n"
            )
            collector = object.__new__(LinuxMetricsCollector)
            collector.sys_root = sys_root
            collector.proc_root = proc_root

            connection_type, hardware, _ipv4, ipv6, mtu, state = collector._read_network_identity("en-test0")

            self.assertEqual(connection_type, "Ethernet")
            self.assertEqual(hardware, "00:11:22:33:44:55")
            self.assertEqual(ipv6, "fe80::211:22ff:fe33:4455")
            self.assertEqual(mtu, 1500)
            self.assertEqual(state, "Up")


if __name__ == "__main__":
    unittest.main()
