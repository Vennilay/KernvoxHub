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
            "top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | cut -d'%' -f1"
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
        exit_code, output, _ = self.ssh.execute("free -m | grep Mem")
        if exit_code != 0 or not output.strip():
            return {"ram_used_mb": 0.0, "ram_total_mb": 0.0, "ram_percent": 0.0}
        
        parts = output.split()
        if len(parts) >= 7:
            total = float(parts[1])
            used = float(parts[2])
            percent = (used / total * 100) if total > 0 else 0.0
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
            "cat /proc/net/dev | grep -E 'eth0|ens|enp' | head -1"
        )
        if exit_code == 0 and output.strip():
            parts = output.split()
            if len(parts) >= 10:
                try:
                    rx_bytes = float(parts[1])
                    tx_bytes = float(parts[9])
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
