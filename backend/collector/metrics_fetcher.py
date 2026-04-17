from typing import Dict, Any, Optional, List
from collector.ssh_client import SSHClient


class MetricsFetcher:
    KILOBYTES_IN_MEGABYTE = 1000.0
    CPU_PROC_STAT_COMMAND = (
        "read _ prev_user prev_nice prev_system prev_idle prev_iowait prev_irq prev_softirq prev_steal _ < /proc/stat; "
        "prev_total=$((prev_user + prev_nice + prev_system + prev_idle + prev_iowait + prev_irq + prev_softirq + prev_steal)); "
        "prev_idle_total=$((prev_idle + prev_iowait)); "
        "sleep 1; "
        "read _ curr_user curr_nice curr_system curr_idle curr_iowait curr_irq curr_softirq curr_steal _ < /proc/stat; "
        "curr_total=$((curr_user + curr_nice + curr_system + curr_idle + curr_iowait + curr_irq + curr_softirq + curr_steal)); "
        "curr_idle_total=$((curr_idle + curr_iowait)); "
        "total_delta=$((curr_total - prev_total)); "
        "idle_delta=$((curr_idle_total - prev_idle_total)); "
        "if [ \"$total_delta\" -le 0 ]; then "
        "echo 0; "
        "else "
        "awk -v total_delta=\"$total_delta\" -v idle_delta=\"$idle_delta\" 'BEGIN { printf \"%.2f\", ((total_delta - idle_delta) / total_delta) * 100 }'; "
        "fi"
    )
    CPU_VMSTAT_COMMAND = "vmstat 1 2 | tail -1 | awk '{print $15}'"

    def __init__(self, ssh_client: SSHClient):
        self.ssh = ssh_client

    def fetch_all(self) -> Optional[Dict[str, Any]]:
        metrics = {
            "cpu_percent": self._get_cpu_percent(),
            "ram_used_mb": 0.0,
            "ram_total_mb": 0.0,
            "ram_percent": 0.0,
            "disk_used_percent": self._get_disk_percent(),
            "network_rx_bytes": 0.0,
            "network_tx_bytes": 0.0,
            "uptime_seconds": self._get_uptime(),
            "is_available": True
        }
        
        ram_metrics = self._get_ram_metrics()
        metrics.update(ram_metrics)
        
        network_metrics = self._get_network_metrics()
        metrics.update(network_metrics)
        
        return metrics
    
    def _get_cpu_percent(self) -> float:
        exit_code, output, _ = self.ssh.execute(self.CPU_PROC_STAT_COMMAND)
        if exit_code == 0 and output.strip():
            try:
                return float(output.strip())
            except ValueError:
                pass
        
        exit_code, output, _ = self.ssh.execute(self.CPU_VMSTAT_COMMAND)
        if exit_code == 0 and output.strip():
            try:
                return 100.0 - float(output.strip())
            except ValueError:
                pass
        
        return 0.0
    
    def _get_ram_metrics(self) -> Dict[str, float]:
        exit_code, output, _ = self.ssh.execute("cat /proc/meminfo")
        if exit_code != 0 or not output.strip():
            return {"ram_used_mb": 0.0, "ram_total_mb": 0.0, "ram_percent": 0.0}

        meminfo = self._parse_meminfo(output)
        total_kb = meminfo.get("MemTotal", 0.0)
        if total_kb <= 0:
            return {"ram_used_mb": 0.0, "ram_total_mb": 0.0, "ram_percent": 0.0}

        used_kb = self._calculate_used_memory_kb(meminfo)
        return {
            "ram_used_mb": round(used_kb / self.KILOBYTES_IN_MEGABYTE, 2),
            "ram_total_mb": round(total_kb / self.KILOBYTES_IN_MEGABYTE, 2),
            "ram_percent": round((used_kb / total_kb) * 100, 2),
        }

    @staticmethod
    def _parse_meminfo(output: str) -> Dict[str, float]:
        meminfo: Dict[str, float] = {}
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 2 or not parts[0].endswith(":"):
                continue

            try:
                meminfo[parts[0][:-1]] = float(parts[1])
            except ValueError:
                continue

        return meminfo

    @staticmethod
    def _calculate_used_memory_kb(meminfo: Dict[str, float]) -> float:
        total_kb = meminfo.get("MemTotal", 0.0)
        free_kb = meminfo.get("MemFree")
        buffers_kb = meminfo.get("Buffers")
        cached_kb = meminfo.get("Cached")
        reclaimable_kb = meminfo.get("SReclaimable")
        shmem_kb = meminfo.get("Shmem")

        if None not in (free_kb, buffers_kb, cached_kb, reclaimable_kb, shmem_kb):
            # Align the "used" figure with htop/free output by excluding reclaimable cache.
            cache_kb = max(cached_kb + reclaimable_kb - shmem_kb, 0.0)
            return max(total_kb - free_kb - buffers_kb - cache_kb, 0.0)

        available_kb = meminfo.get("MemAvailable")
        if available_kb is not None:
            return max(total_kb - available_kb, 0.0)

        return 0.0
    
    def _get_disk_percent(self) -> float:
        exit_code, output, _ = self.ssh.execute("df / | tail -1 | awk '{print $5}' | cut -d'%' -f1")
        if exit_code == 0 and output.strip():
            try:
                return float(output.strip())
            except ValueError:
                pass
        return 0.0
    
    def _get_uptime(self) -> float:
        exit_code, output, _ = self.ssh.execute("cat /proc/uptime | awk '{print $1}'")
        if exit_code == 0 and output.strip():
            try:
                return float(output.strip())
            except ValueError:
                pass
        return 0.0
    
    def _get_network_metrics(self) -> Dict[str, float]:
        exit_code, output, _ = self.ssh.execute(
            "ip route show default 2>/dev/null | awk '/default/ {print $5; exit}'"
        )
        if exit_code == 0 and output.strip():
            interface = output.strip()
            exit_code, output, _ = self.ssh.execute(
                f"awk -F'[: ]+' '$1 ~ /^{interface}$/ {{print $3, $11}}' /proc/net/dev"
            )
            if exit_code == 0 and output.strip():
                parts = output.split()
                if len(parts) >= 2:
                    try:
                        return {
                            "network_rx_bytes": float(parts[0]),
                            "network_tx_bytes": float(parts[1]),
                        }
                    except ValueError:
                        pass

        exit_code, output, _ = self.ssh.execute(
            "awk -F'[: ]+' '$1 !~ /^(lo|)$/ {rx += $3; tx += $11} END {print rx+0, tx+0}' /proc/net/dev"
        )
        if exit_code == 0 and output.strip():
            parts = output.split()
            if len(parts) >= 2:
                try:
                    rx_bytes = float(parts[0])
                    tx_bytes = float(parts[1])
                    return {
                        "network_rx_bytes": rx_bytes,
                        "network_tx_bytes": tx_bytes
                    }
                except (ValueError, IndexError):
                    pass
        
        return {"network_rx_bytes": 0.0, "network_tx_bytes": 0.0}

    def get_processes(self, limit: int = 50) -> List[Dict[str, Any]]:
        exit_code, output, _ = self.ssh.execute(
            f"ps aux --sort=-%cpu | head -{limit + 1}"
        )
        if exit_code != 0 or not output.strip():
            return []

        processes = []
        lines = output.strip().split("\n")
        
        for line in lines[1:]:
            parts = line.split(None, 10)
            if len(parts) >= 11:
                try:
                    processes.append({
                        "pid": int(parts[1]),
                        "user": parts[0],
                        "cpu_percent": float(parts[2]),
                        "memory_percent": float(parts[3]),
                        "command": parts[10][:200]
                    })
                except (ValueError, IndexError):
                    continue

        return processes[:limit]
