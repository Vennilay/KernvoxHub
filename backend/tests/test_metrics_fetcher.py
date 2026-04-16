from collector.metrics_fetcher import MetricsFetcher


class FakeSSHClient:
    def __init__(self, responses):
        self.responses = responses

    def execute(self, command: str, timeout: int = 10):
        return self.responses.get(command, (-1, "", "unknown command"))


def test_ram_metrics_use_memavailable():
    command = (
        "awk '"
        "/^MemTotal:/ { total_kb = $2 } "
        "/^MemAvailable:/ { available_kb = $2 } "
        "END { "
        "if (total_kb <= 0) { "
        "print \"0 0 0\"; "
        "} else { "
        "used_kb = total_kb - available_kb; "
        "printf \"%.2f %.2f %.2f\", used_kb / 1024, total_kb / 1024, (used_kb / total_kb) * 100; "
        "} "
        "}' /proc/meminfo"
    )
    ssh = FakeSSHClient(
        {
            command: (0, "1024.00 2048.00 50.00", ""),
        }
    )

    fetcher = MetricsFetcher(ssh)

    assert fetcher._get_ram_metrics() == {
        "ram_used_mb": 1024.0,
        "ram_total_mb": 2048.0,
        "ram_percent": 50.0,
    }


def test_cpu_percent_uses_proc_stat_delta():
    command = (
        "prev=$(grep '^cpu ' /proc/stat); "
        "sleep 1; "
        "curr=$(grep '^cpu ' /proc/stat); "
        "awk '"
        "BEGIN {"
        "split(prev, a, \" \"); "
        "split(curr, b, \" \"); "
        "for (i = 2; i <= 9; i++) { "
        "prev_total += a[i]; "
        "curr_total += b[i]; "
        "} "
        "prev_idle = a[5] + a[6]; "
        "curr_idle = b[5] + b[6]; "
        "total_delta = curr_total - prev_total; "
        "idle_delta = curr_idle - prev_idle; "
        "if (total_delta <= 0) { "
        "print 0; "
        "} else { "
        "printf \"%.2f\", ((total_delta - idle_delta) / total_delta) * 100; "
        "} "
        "}' prev=\"$prev\" curr=\"$curr\""
    )
    ssh = FakeSSHClient(
        {
            command: (0, "37.50", ""),
        }
    )

    fetcher = MetricsFetcher(ssh)

    assert fetcher._get_cpu_percent() == 37.5
