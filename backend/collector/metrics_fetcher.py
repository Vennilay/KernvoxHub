from typing import Dict, Any, Optional, List
from collector.ssh_client import SSHClient


class MetricsFetcher:
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
        exit_code, output, _ = self.ssh.execute(
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
        if exit_code == 0 and output.strip():
            try:
                return float(output.strip())
            except ValueError:
                pass
        
        exit_code, output, _ = self.ssh.execute(
            "vmstat 1 2 | tail -1 | awk '{print $15}'"
        )
        if exit_code == 0 and output.strip():
            try:
                return 100.0 - float(output.strip())
            except ValueError:
                pass
        
        return 0.0
    
    def _get_ram_metrics(self) -> Dict[str, float]:
        exit_code, output, _ = self.ssh.execute(
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
        if exit_code != 0 or not output.strip():
            return {"ram_used_mb": 0.0, "ram_total_mb": 0.0, "ram_percent": 0.0}

        parts = output.split()
        if len(parts) >= 3:
            used = float(parts[0])
            total = float(parts[1])
            percent = float(parts[2])
            return {
                "ram_used_mb": used,
                "ram_total_mb": total,
                "ram_percent": percent
            }
        
        return {"ram_used_mb": 0.0, "ram_total_mb": 0.0, "ram_percent": 0.0}
    
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
