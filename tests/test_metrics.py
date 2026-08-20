import unittest
import signal
import subprocess
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch

from tmog_linux.metrics import (
    LinuxMetricsCollector,
    ServiceInfo,
    StartupEntry,
    application_id_from_control_group,
    cpu_percent,
    format_bytes,
    parse_cpu_stat,
    parse_diskstats,
    parse_diskstats_by_device,
    parse_default_route_interface,
    parse_drm_fdinfo,
    parse_meminfo,
    parse_netdev,
    parse_netdev_interfaces,
    parse_nvidia_smi_csv,
    parse_pci_device_name,
    parse_process_stat,
    parse_systemctl_services,
    service_membership_from_control_group,
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
        self.assertEqual(parse_diskstats_by_device(text, {"sda"}), {"sda": (5120, 10240, 30)})

    def test_netdev_excludes_loopback(self):
        text = "Inter-| Receive | Transmit\n face |bytes |bytes\n lo: 100 0 0 0 0 0 0 0 200 0\n eth0: 300 0 0 0 0 0 0 0 400 0\n"
        self.assertEqual(parse_netdev(text), (300, 400))
        self.assertEqual(parse_netdev_interfaces(text), {"eth0": (300, 400)})

    def test_per_disk_snapshots_keep_independent_rates_and_identity(self):
        with TemporaryDirectory() as directory:
            sys_root = Path(directory)
            disk = sys_root / "block/nvme0n1"
            (disk / "device").mkdir(parents=True)
            (disk / "queue").mkdir()
            (disk / "device/model").write_text("Demo NVMe\n")
            (disk / "size").write_text("2000\n")
            (disk / "queue/rotational").write_text("0\n")
            collector = object.__new__(LinuxMetricsCollector)
            collector.sys_root = sys_root
            collector._physical_devices = {"nvme0n1"}
            collector._previous_disks = {"nvme0n1": (1000, 2000, 10)}

            snapshots = collector._read_disk_snapshots({"nvme0n1": (5000, 8000, 260)}, 0.5)

            self.assertEqual(len(snapshots), 1)
            snapshot = snapshots[0]
            self.assertEqual(snapshot.model, "Demo NVMe")
            self.assertEqual(snapshot.device_type, "NVMe")
            self.assertEqual(snapshot.capacity, 2000 * 512)
            self.assertEqual(snapshot.read_bps, 8000.0)
            self.assertEqual(snapshot.write_bps, 12000.0)
            self.assertEqual(snapshot.busy_percent, 50.0)

    def test_per_interface_snapshots_prefer_default_route_and_keep_rates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sys_root = root / "sys"
            proc_root = root / "proc"
            for name, state, speed in (("eno1", "up", "1000"), ("wlan0", "down", "300")):
                interface = sys_root / "class/net" / name
                (interface / "device").mkdir(parents=True)
                (interface / "address").write_text(f"00:11:22:33:44:{'55' if name == 'eno1' else '66'}")
                (interface / "mtu").write_text("1500")
                (interface / "operstate").write_text(state)
                (interface / "speed").write_text(speed)
            (sys_root / "class/net/wlan0/wireless").mkdir()
            (proc_root / "net").mkdir(parents=True)
            (proc_root / "net/route").write_text(
                "Iface Destination Gateway Flags RefCnt Use Metric Mask\n"
                "eno1 00000000 0100000A 0003 0 0 10 00000000\n"
            )
            (proc_root / "net/if_inet6").write_text("")
            collector = object.__new__(LinuxMetricsCollector)
            collector.sys_root = sys_root
            collector.proc_root = proc_root
            collector._previous_networks = {"eno1": (1000, 2000), "wlan0": (3000, 4000)}

            snapshots = collector._read_network_snapshots(
                {"eno1": (5000, 8000), "wlan0": (3500, 4500)},
                0.5,
            )

            self.assertEqual([item.identifier for item in snapshots], ["eno1", "wlan0"])
            self.assertTrue(snapshots[0].primary)
            self.assertEqual(snapshots[0].connection_type, "Ethernet")
            self.assertEqual(snapshots[0].link_speed_mbps, 1000)
            self.assertEqual(snapshots[0].receive_bps, 8000.0)
            self.assertEqual(snapshots[0].send_bps, 12000.0)
            self.assertEqual(snapshots[1].connection_type, "Wi-Fi")

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

    def test_nvidia_smi_watchdog_disables_a_hung_provider(self):
        release_query = threading.Event()
        collector = object.__new__(LinuxMetricsCollector)
        collector._nvidia_smi_path = "nvidia-smi"
        collector._nvidia_smi_disabled = False
        collector._nvidia_smi_watchdog_seconds = 0.02

        def hung_query(*_args, **_kwargs):
            release_query.wait(1.0)
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")

        try:
            with patch("tmog_linux.metrics.subprocess.run", side_effect=hung_query) as run:
                started = time.monotonic()
                self.assertEqual(collector._query_nvidia_smi(("index", "name")), [])
                self.assertLess(time.monotonic() - started, 0.25)
                self.assertTrue(collector._nvidia_smi_disabled)
                self.assertEqual(collector._query_nvidia_smi(("index", "name")), [])
                self.assertEqual(run.call_count, 1)
        finally:
            release_query.set()

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

    def test_named_process_signals_are_whitelisted(self):
        with patch("tmog_linux.metrics.os.kill") as kill:
            for signal_name in ("HUP", "INT", "TERM", "KILL", "USR1", "USR2"):
                LinuxMetricsCollector.send_process_signal(4242, signal_name)
            self.assertEqual(
                kill.call_args_list,
                [
                    call(4242, signal.SIGHUP),
                    call(4242, signal.SIGINT),
                    call(4242, signal.SIGTERM),
                    call(4242, signal.SIGKILL),
                    call(4242, signal.SIGUSR1),
                    call(4242, signal.SIGUSR2),
                ],
            )
        with self.assertRaises(ValueError):
            LinuxMetricsCollector.send_process_signal(4242, "SEGV")

    def test_cgroup_application_and_service_membership(self):
        self.assertEqual(
            application_id_from_control_group(
                "/user.slice/user-1000.slice/user@1000.service/app.slice/"
                "app-gnome-org.gnome.Terminal-4821.scope"
            ),
            "org.gnome.Terminal",
        )
        self.assertEqual(
            service_membership_from_control_group("/system.slice/NetworkManager.service"),
            ("system", "NetworkManager.service"),
        )
        self.assertEqual(
            service_membership_from_control_group(
                "/user.slice/user-1000.slice/user@1000.service/app.slice/xdg-desktop-portal.service"
            ),
            ("user", "xdg-desktop-portal.service"),
        )
        self.assertIsNone(
            service_membership_from_control_group(
                "/user.slice/user-1000.slice/user@1000.service/app.slice/"
                "app-gnome-org.gnome.Terminal-4821.scope"
            )
        )

    def test_systemctl_service_parsing_and_control_scope(self):
        text = (
            "● failed.service loaded failed failed Demonstration failure\n"
            "ssh.service loaded active running OpenSSH server\n"
        )
        services = parse_systemctl_services(text, "system")
        self.assertEqual(
            [(item.unit, item.active, item.state, item.scope) for item in services],
            [
                ("failed.service", "failed", "failed", "system"),
                ("ssh.service", "active", "running", "system"),
            ],
        )

        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch("tmog_linux.metrics.subprocess.run", return_value=completed) as run:
            LinuxMetricsCollector.control_service(
                ServiceInfo("demo.service", "inactive", "dead", "Demo", "user"),
                "start",
            )
            self.assertEqual(run.call_args.args[0], ["systemctl", "--user", "start", "demo.service"])

        denied = subprocess.CompletedProcess([], 1, stdout="", stderr="Access denied")
        with patch("tmog_linux.metrics.subprocess.run", return_value=denied):
            with self.assertRaisesRegex(RuntimeError, "Access denied"):
                LinuxMetricsCollector.control_service(
                    ServiceInfo("demo.service", "active", "running", "Demo", "system"),
                    "stop",
                )

    def test_service_collection_queries_user_and_system_managers(self):
        user_result = subprocess.CompletedProcess(
            [],
            0,
            stdout="portal.service loaded active running Desktop portal\n",
            stderr="",
        )
        system_result = subprocess.CompletedProcess(
            [],
            0,
            stdout="ssh.service loaded active running OpenSSH server\n",
            stderr="",
        )
        with patch("tmog_linux.metrics.subprocess.run", side_effect=[user_result, system_result]) as run:
            services = LinuxMetricsCollector.services()
        self.assertEqual([(item.scope, item.unit) for item in services], [("user", "portal.service"), ("system", "ssh.service")])
        self.assertEqual(run.call_args_list[0].args[0][:2], ["systemctl", "--user"])
        self.assertEqual(run.call_args_list[1].args[0][0], "systemctl")
        self.assertNotIn("--user", run.call_args_list[1].args[0])

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

    def test_startup_entries_honor_user_override_and_can_be_reenabled(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            user_config = root / "user"
            system_config = root / "system"
            user_autostart = user_config / "autostart"
            system_autostart = system_config / "autostart"
            user_autostart.mkdir(parents=True)
            system_autostart.mkdir(parents=True)
            system_entry = system_autostart / "example.desktop"
            system_entry.write_text(
                "[Desktop Entry]\nType=Application\nName=Example\nExec=example --start\n",
                encoding="utf-8",
            )

            with patch.dict(
                "os.environ",
                {"XDG_CONFIG_HOME": str(user_config), "XDG_CONFIG_DIRS": str(system_config)},
                clear=False,
            ):
                entries = LinuxMetricsCollector.startup_entries()
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0].source, "System")
                self.assertTrue(entries[0].enabled)

                override = LinuxMetricsCollector.set_startup_enabled(entries[0], False)
                self.assertEqual(override, user_autostart / "example.desktop")
                disabled = LinuxMetricsCollector.startup_entries()[0]
                self.assertEqual(disabled.source, "User override")
                self.assertFalse(disabled.enabled)

                LinuxMetricsCollector.set_startup_enabled(disabled, True)
                enabled = LinuxMetricsCollector.startup_entries()[0]
                self.assertTrue(enabled.enabled)
                self.assertEqual(enabled.command, "example --start")

    def test_user_startup_entry_can_be_disabled_in_place(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            user_config = root / "user"
            user_autostart = user_config / "autostart"
            user_autostart.mkdir(parents=True)
            desktop_file = user_autostart / "personal.desktop"
            desktop_file.write_text(
                "[Desktop Entry]\nType=Application\nName=Personal\nExec=personal %u\n",
                encoding="utf-8",
            )
            entry = StartupEntry("Personal", "personal %u", "User", True, desktop_file)

            with patch.dict(
                "os.environ",
                {"XDG_CONFIG_HOME": str(user_config), "XDG_CONFIG_DIRS": str(root / "system")},
                clear=False,
            ):
                target = LinuxMetricsCollector.set_startup_enabled(entry, False)
                self.assertEqual(target, desktop_file)
                disabled = LinuxMetricsCollector.startup_entries()[0]
                self.assertFalse(disabled.enabled)
                self.assertEqual(disabled.command, "personal %u")

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
