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
    """Проверяет расчёт RAM как Linux working set.

    Что делает: отдаёт fake `/proc/meminfo` с MemFree/Buffers/Cached/SReclaimable/Shmem.
    Ожидаемая реакция: fetcher считает used/total/percent так же, как ожидается для htop/free-подобной логики.
    """
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
    """Проверяет fallback RAM-расчёта через MemAvailable.

    Что делает: отдаёт сокращённый `/proc/meminfo`, где нет cache breakdown полей.
    Ожидаемая реакция: fetcher использует `MemTotal - MemAvailable` и возвращает корректные MB/percent.
    """
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
    """Проверяет основной расчёт CPU по `/proc/stat` delta.

    Что делает: fake SSH возвращает успешный результат команды `CPU_PROC_STAT_COMMAND`.
    Ожидаемая реакция: fetcher возвращает float-значение из proc-stat ветки без fallback на vmstat.
    """
    command = MetricsFetcher.CPU_PROC_STAT_COMMAND
    ssh = FakeSSHClient(
        {
            command: (0, "37.50", ""),
        }
    )

    fetcher = MetricsFetcher(ssh)

    assert fetcher._get_cpu_percent() == 37.5


def test_cpu_percent_falls_back_to_vmstat():
    """Проверяет fallback CPU-расчёта через vmstat.

    Что делает: имитирует отказ proc-stat команды и успешный вывод idle percent из `vmstat`.
    Ожидаемая реакция: fetcher возвращает `100 - idle`, сохраняя метрики на системах без доступного proc-stat сценария.
    """
    ssh = FakeSSHClient(
        {
            MetricsFetcher.CPU_PROC_STAT_COMMAND: (-1, "", "proc stat failed"),
            MetricsFetcher.CPU_VMSTAT_COMMAND: (0, "12", ""),
        }
    )

    fetcher = MetricsFetcher(ssh)

    assert fetcher._get_cpu_percent() == 88.0


def test_process_cpu_percent_is_normalized_by_cpu_core_count():
    """Проверяет нормализацию CPU процессов для Android endpoint.

    Что делает: имитирует `ps aux`, где многопоточный процесс показывает `600%` на 8 CPU.
    Ожидаемая реакция: fetcher отдаёт процент от общей мощности сервера, то есть `75%`, а не raw значение `ps`.
    """
    ssh = FakeSSHClient(
        {
            MetricsFetcher.CPU_CORE_COUNT_COMMAND: (0, "8\n", ""),
            "ps aux --sort=-%cpu | head -3": (
                0,
                "\n".join(
                    [
                        "USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND",
                        "root 101 600.0 2.5 1000 100 ? Sl 10:00 1:00 worker",
                        "www 102 12.5 1.0 1000 100 ? S 10:00 0:01 nginx: worker process",
                    ]
                ),
                "",
            ),
        }
    )

    processes = MetricsFetcher(ssh).get_processes(limit=2)

    assert processes[0]["cpu_percent"] == 75.0
    assert processes[1]["cpu_percent"] == 1.56


def test_process_cpu_percent_is_capped_after_normalization():
    """Проверяет верхнюю границу CPU процесса.

    Что делает: имитирует некорректно большое raw `%CPU`.
    Ожидаемая реакция: API-значение остаётся в диапазоне `0..100`.
    """
    ssh = FakeSSHClient(
        {
            MetricsFetcher.CPU_CORE_COUNT_COMMAND: (0, "4\n", ""),
            "ps aux --sort=-%cpu | head -2": (
                0,
                "\n".join(
                    [
                        "USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND",
                        "root 101 900.0 2.5 1000 100 ? Sl 10:00 1:00 worker",
                    ]
                ),
                "",
            ),
        }
    )

    processes = MetricsFetcher(ssh).get_processes(limit=1)

    assert processes[0]["cpu_percent"] == 100.0


def test_network_metrics_parse_default_interface_with_leading_spaces():
    """Проверяет парсинг network-счётчиков default interface.

    Что делает: имитирует default route `eth0` и вывод awk по `/proc/net/dev` со значениями RX/TX.
    Ожидаемая реакция: fetcher возвращает ненулевые `network_rx_bytes` и `network_tx_bytes`, не ломаясь на ведущих пробелах.
    """
    fetcher = MetricsFetcher(NetworkSSHClient())

    assert fetcher._get_network_metrics() == {
        "network_rx_bytes": 61625988655.0,
        "network_tx_bytes": 52465603776.0,
    }


def test_network_metrics_fallback_sums_non_loopback_interfaces():
    """Проверяет fallback network-метрик без default route.

    Что делает: имитирует отсутствие default interface и успешную сумму всех non-loopback интерфейсов.
    Ожидаемая реакция: fetcher возвращает суммарные RX/TX вместо `0/0`.
    """
    fetcher = MetricsFetcher(FallbackNetworkSSHClient())

    assert fetcher._get_network_metrics() == {
        "network_rx_bytes": 61625988655.0,
        "network_tx_bytes": 52465603776.0,
    }
