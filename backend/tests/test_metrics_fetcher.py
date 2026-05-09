from collector.metrics_fetcher import MetricsFetcher


class FakeSSHClient:
    def __init__(self, responses):
        self.responses = responses

    def execute(self, command: str, timeout: int = 10):
        return self.responses.get(command, (-1, "", "unknown command"))


class NetworkSSHClient:
    def execute(self, command: str, timeout: int = 10):
        if command.startswith("ip route show default"):
            return 0, "eth0\n", ""
        if "-v iface=eth0" in command:
            return 0, "61625988655 52465603776\n", ""
        return -1, "", "unknown command"


class FallbackNetworkSSHClient:
    def execute(self, command: str, timeout: int = 10):
        if command.startswith("ip route show default"):
            return 1, "", ""
        if "END {print rx+0, tx+0}" in command:
            return 0, "61625988655 52465603776\n", ""
        return -1, "", "unknown command"


def test_ram_metrics_match_linux_working_set():
    command = "cat /proc/meminfo"
    ssh = FakeSSHClient(
        {
            command: (
                0,
                "\n".join(
                    [
                        "MemTotal:        4096000 kB",
                        "MemFree:          512000 kB",
                        "MemAvailable:    3072000 kB",
                        "Buffers:          128000 kB",
                        "Cached:          2048000 kB",
                        "SReclaimable:     256000 kB",
                        "Shmem:            128000 kB",
                    ]
                ),
                "",
            ),
        }
    )

    fetcher = MetricsFetcher(ssh)

    assert fetcher._get_ram_metrics() == {
        "ram_used_mb": 1280.0,
        "ram_total_mb": 4096.0,
        "ram_percent": 31.25,
    }


def test_ram_metrics_fall_back_to_memavailable_when_cache_fields_are_missing():
    command = "cat /proc/meminfo"
    ssh = FakeSSHClient(
        {
            command: (
                0,
                "\n".join(
                    [
                        "MemTotal:        2048000 kB",
                        "MemAvailable:    1024000 kB",
                    ]
                ),
                "",
            ),
        }
    )

    fetcher = MetricsFetcher(ssh)

    assert fetcher._get_ram_metrics() == {
        "ram_used_mb": 1024.0,
        "ram_total_mb": 2048.0,
        "ram_percent": 50.0,
    }


def test_cpu_percent_uses_proc_stat_delta():
    command = MetricsFetcher.CPU_PROC_STAT_COMMAND
    ssh = FakeSSHClient(
        {
            command: (0, "37.50", ""),
        }
    )

    fetcher = MetricsFetcher(ssh)

    assert fetcher._get_cpu_percent() == 37.5


def test_cpu_percent_falls_back_to_vmstat():
    ssh = FakeSSHClient(
        {
            MetricsFetcher.CPU_PROC_STAT_COMMAND: (-1, "", "proc stat failed"),
            MetricsFetcher.CPU_VMSTAT_COMMAND: (0, "12", ""),
        }
    )

    fetcher = MetricsFetcher(ssh)

    assert fetcher._get_cpu_percent() == 88.0


def test_network_metrics_parse_default_interface_with_leading_spaces():
    fetcher = MetricsFetcher(NetworkSSHClient())

    assert fetcher._get_network_metrics() == {
        "network_rx_bytes": 61625988655.0,
        "network_tx_bytes": 52465603776.0,
    }


def test_network_metrics_fallback_sums_non_loopback_interfaces():
    fetcher = MetricsFetcher(FallbackNetworkSSHClient())

    assert fetcher._get_network_metrics() == {
        "network_rx_bytes": 61625988655.0,
        "network_tx_bytes": 52465603776.0,
    }
