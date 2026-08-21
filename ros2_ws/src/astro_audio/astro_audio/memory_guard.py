#!/usr/bin/env python3
"""ASTRO V1 — System-Wide Memory Pressure Monitor & XTTS Resource Admission Controller.

Provides non-blocking, production-grade memory inspection, process RSS tracking,
Linux OOM kill detection, and admission gating to protect the robot's real-time
critical paths from XTTS worker memory exhaustion on Jetson Orin Nano (8GB Unified Memory).
"""

import os
import sys
import glob
import time
from typing import Any, Dict, Optional, Tuple

try:
    import psutil
except ImportError:
    psutil = None


class SystemMemoryGuard:
    """Monitors system-wide RAM, Swap, and Process RSS to enforce XTTS admission gating."""

    def __init__(
        self,
        min_available_ram_mb: Optional[float] = None,
        max_swap_used_percent: Optional[float] = None,
        max_ram_used_percent: Optional[float] = None,
    ):
        self.min_available_ram_mb = float(
            min_available_ram_mb
            if min_available_ram_mb is not None
            else os.getenv("XTTS_MIN_AVAILABLE_RAM_MB", "2200.0")
        )
        self.max_swap_used_percent = float(
            max_swap_used_percent
            if max_swap_used_percent is not None
            else os.getenv("XTTS_MAX_SWAP_USED_PERCENT", "70.0")
        )
        self.max_ram_used_percent = float(
            max_ram_used_percent
            if max_ram_used_percent is not None
            else os.getenv("XTTS_MAX_RAM_USED_PERCENT", "80.0")
        )
        # Çekirdeğin bildirdiği bellek duraklama oranı (PSI). "full avg60", son 60
        # saniyede TÜM görevlerin bellek beklerken durduğu sürenin yüzdesi — anlık
        # baskının doğrudan ölçüsü. Takas doluluğunun aksine geçmişe takılı kalmaz.
        self.max_mem_psi_full_avg60 = float(
            os.getenv("XTTS_MAX_MEM_PSI_FULL_AVG60", "10.0")
        )
        # Takas doluluğu TEK BAŞINA reddetme sebebi değildir; sistemin o an fiilen
        # takastan sayfa okuyor olması da gerekir (sayfa/sn).
        self.min_swap_in_pages_per_s = float(
            os.getenv("XTTS_MIN_SWAP_IN_PAGES_PER_S", "100.0")
        )

        self._oom_killed_count = 0
        self._oom_quarantine = False
        self._last_swap_sample: Optional[Tuple[float, float]] = None

    def record_oom_kill(self, pid: Optional[int] = None, details: str = ""):
        """Records an OOM kill event and latches quarantine for the current session."""
        self._oom_killed_count += 1
        self._oom_quarantine = True

    def reset_oom_quarantine(self):
        """Allows manual reset of OOM quarantine (e.g. via service or admin)."""
        self._oom_quarantine = False

    @property
    def is_oom_quarantined(self) -> bool:
        return self._oom_quarantine

    @property
    def oom_killed_count(self) -> int:
        return self._oom_killed_count

    def get_process_rss_mb(self, pid: Any) -> float:
        """Returns RSS memory of given PID in megabytes."""
        if not isinstance(pid, int) or pid <= 0:
            return 0.0
        try:
            # Fast Linux /proc lookup
            status_path = f"/proc/{pid}/status"
            if os.path.exists(status_path):
                with open(status_path, "r", encoding="utf-8", errors="ignore") as fp:
                    for line in fp:
                        if line.startswith("VmRSS:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                return float(parts[1]) / 1024.0
            # Psutil fallback
            if psutil is not None:
                p = psutil.Process(pid)
                return p.memory_info().rss / (1024.0 * 1024.0)
        except Exception:
            pass
        return 0.0

    @staticmethod
    def read_mem_psi_full_avg60() -> Optional[float]:
        """/proc/pressure/memory'den "full avg60" değerini döndürür (yoksa None)."""
        try:
            with open("/proc/pressure/memory", "r", encoding="utf-8") as fp:
                for line in fp:
                    if not line.startswith("full "):
                        continue
                    for field in line.split():
                        if field.startswith("avg60="):
                            return float(field.split("=", 1)[1])
        except Exception:
            pass
        return None

    def read_swap_in_rate(self) -> Optional[float]:
        """Son çağrıdan bu yana takastan okunan sayfa/sn oranı.

        İlk çağrıda karşılaştırılacak örnek olmadığı için None döner; bu durumda
        takas kuralı uygulanmaz (bilinmeyen bir oranla reddetmek yanlış olur).
        """
        try:
            with open("/proc/vmstat", "r", encoding="utf-8") as fp:
                pswpin = None
                for line in fp:
                    if line.startswith("pswpin "):
                        pswpin = float(line.split()[1])
                        break
            if pswpin is None:
                return None
        except Exception:
            return None

        now = time.monotonic()
        prev = self._last_swap_sample
        self._last_swap_sample = (now, pswpin)
        if prev is None:
            return None
        dt = now - prev[0]
        if dt <= 0.0:
            return None
        return max(0.0, (pswpin - prev[1]) / dt)

    def get_memory_snapshot(self, xtts_pid: Optional[int] = None) -> Dict[str, Any]:
        """Collects complete snapshot of system memory, swap, and process RSS."""
        mem_total_mb = 0.0
        mem_free_mb = 0.0
        mem_avail_mb = 0.0
        mem_used_mb = 0.0
        swap_total_mb = 0.0
        swap_free_mb = 0.0
        swap_used_mb = 0.0
        swap_used_pct = 0.0
        ram_used_pct = 0.0

        # 1. Inspect Linux /proc/meminfo
        if os.path.exists("/proc/meminfo"):
            try:
                meminfo = {}
                with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as fp:
                    for line in fp:
                        parts = line.split(":")
                        if len(parts) == 2:
                            k = parts[0].strip()
                            v_parts = parts[1].strip().split()
                            if v_parts:
                                meminfo[k] = float(v_parts[0])  # in kB

                mem_total_mb = meminfo.get("MemTotal", 0.0) / 1024.0
                mem_free_mb = meminfo.get("MemFree", 0.0) / 1024.0
                mem_avail_mb = meminfo.get("MemAvailable", mem_free_mb + (meminfo.get("Cached", 0.0) / 1024.0)) / 1024.0
                mem_used_mb = max(0.0, mem_total_mb - mem_avail_mb)

                swap_total_mb = meminfo.get("SwapTotal", 0.0) / 1024.0
                swap_free_mb = meminfo.get("SwapFree", 0.0) / 1024.0
                swap_used_mb = max(0.0, swap_total_mb - swap_free_mb)
            except Exception:
                pass

        # 2. psutil fallback (if /proc/meminfo unavailable or incomplete)
        if mem_total_mb == 0.0 and psutil is not None:
            try:
                vm = psutil.virtual_memory()
                sm = psutil.swap_memory()
                mem_total_mb = vm.total / (1024.0 * 1024.0)
                mem_avail_mb = vm.available / (1024.0 * 1024.0)
                mem_used_mb = (vm.total - vm.available) / (1024.0 * 1024.0)
                swap_total_mb = sm.total / (1024.0 * 1024.0)
                swap_free_mb = sm.free / (1024.0 * 1024.0)
                swap_used_mb = sm.used / (1024.0 * 1024.0)
            except Exception:
                pass

        # Default fallback for virtual/test environments
        if mem_total_mb == 0.0:
            mem_total_mb = 7600.0
            mem_avail_mb = 4000.0
            mem_used_mb = 3600.0
            swap_total_mb = 3800.0
            swap_free_mb = 2000.0
            swap_used_mb = 1800.0

        if swap_total_mb > 0:
            swap_used_pct = (swap_used_mb / swap_total_mb) * 100.0
        if mem_total_mb > 0:
            ram_used_pct = (mem_used_mb / mem_total_mb) * 100.0

        # 3. Process RSS discovery
        astro_rss_mb = self.get_process_rss_mb(os.getpid())
        xtts_rss_mb = self.get_process_rss_mb(xtts_pid) if xtts_pid else 0.0
        oak_rss_mb = 0.0
        vision_rss_mb = 0.0
        audio_rss_mb = 0.0

        if os.path.exists("/proc"):
            try:
                for cmd_file in glob.glob("/proc/[0-9]*/cmdline"):
                    try:
                        with open(cmd_file, "rb") as fp:
                            cmd_bytes = fp.read()
                        cmd_text = cmd_bytes.replace(b"\x00", b" ").decode("utf-8", errors="ignore").lower()
                        if not cmd_text:
                            continue
                        
                        pid_str = cmd_file.split("/")[2]
                        p_id = int(pid_str)
                        if p_id == os.getpid() or (xtts_pid and p_id == xtts_pid):
                            continue

                        if "depthai" in cmd_text or "oak" in cmd_text:
                            oak_rss_mb += self.get_process_rss_mb(p_id)
                        elif "vision" in cmd_text or "face_detector" in cmd_text:
                            vision_rss_mb += self.get_process_rss_mb(p_id)
                        elif "audio_stream" in cmd_text or "audio_capture" in cmd_text:
                            audio_rss_mb += self.get_process_rss_mb(p_id)
                    except Exception:
                        continue
            except Exception:
                pass

        mem_psi_full_avg60 = self.read_mem_psi_full_avg60()
        swap_in_rate = self.read_swap_in_rate()

        return {
            "mem_psi_full_avg60": mem_psi_full_avg60,
            "swap_in_pages_per_s": None if swap_in_rate is None else round(swap_in_rate, 1),
            "system_total_ram_mb": round(mem_total_mb, 1),
            "system_available_ram_mb": round(mem_avail_mb, 1),
            "system_used_ram_mb": round(mem_used_mb, 1),
            "ram_used_percent": round(ram_used_pct, 1),
            "swap_total_mb": round(swap_total_mb, 1),
            "swap_used_mb": round(swap_used_mb, 1),
            "swap_free_mb": round(swap_free_mb, 1),
            "swap_used_percent": round(swap_used_pct, 1),
            "astro_rss_mb": round(astro_rss_mb, 1),
            "xtts_rss_mb": round(xtts_rss_mb, 1),
            "oak_rss_mb": round(oak_rss_mb, 1),
            "vision_rss_mb": round(vision_rss_mb, 1),
            "audio_rss_mb": round(audio_rss_mb, 1),
            "oom_quarantine": self._oom_quarantine,
            "oom_killed_count": self._oom_killed_count,
        }

    def check_xtts_admission(self, xtts_pid: Optional[int] = None) -> Tuple[bool, str, Dict[str, Any]]:
        """Evaluates whether system has sufficient memory headroom to spawn/run XTTS worker."""
        snapshot = self.get_memory_snapshot(xtts_pid)

        # 1. Quarantine check (Prior OOM Kill in session)
        if self._oom_quarantine:
            reason = "session_oom_quarantine (previous Linux OOM kill detected in session)"
            return False, reason, snapshot

        # 2. Available RAM check
        avail_ram = snapshot["system_available_ram_mb"]
        if avail_ram < self.min_available_ram_mb:
            reason = f"insufficient_available_ram ({avail_ram:.0f}MB < {self.min_available_ram_mb:.0f}MB)"
            return False, reason, snapshot

        # 3. RAM Usage percentage check
        ram_pct = snapshot["ram_used_percent"]
        if ram_pct > self.max_ram_used_percent:
            reason = f"excessive_ram_usage ({ram_pct:.1f}% > {self.max_ram_used_percent:.1f}%)"
            return False, reason, snapshot

        # 4. Sustained memory stall (PSI) — çekirdeğin bildirdiği ANLIK baskı.
        psi = snapshot.get("mem_psi_full_avg60")
        if psi is not None and psi > self.max_mem_psi_full_avg60:
            reason = f"sustained_memory_stall (PSI full avg60 {psi:.1f} > {self.max_mem_psi_full_avg60:.1f})"
            return False, reason, snapshot

        # 5. Takas kuralı: doluluk TEK BAŞINA yeterli değil.
        #
        # Linux takasa yazdığı soğuk sayfaları RAM sonradan boşalsa bile geri
        # çekmez; uzun süredir açık bir sistemde takas doluluğu kalıcı olarak
        # yüksek kalır. Yani "%80 dolu", "şu an sıkışığız" demek değil — geçmişin
        # kalıntısıdır ve tek başına reddetme sebebi yapılırsa 3 GB boş RAM'i olan
        # makinede bile XTTS hiç denenmeden elenir.
        #
        # Bu yüzden doluluğun yanında sistemin o an fiilen takastan sayfa okuyor
        # olmasını da arıyoruz. Oran ölçülemiyorsa (ilk örnek) kural uygulanmaz.
        swap_pct = snapshot["swap_used_percent"]
        swap_in_rate = snapshot.get("swap_in_pages_per_s")
        if (
            snapshot["swap_total_mb"] > 0
            and swap_pct > self.max_swap_used_percent
            and swap_in_rate is not None
            and swap_in_rate > self.min_swap_in_pages_per_s
        ):
            reason = (
                f"active_swap_thrashing (swap {swap_pct:.1f}% dolu ve "
                f"{swap_in_rate:.0f} sayfa/sn okunuyor > {self.min_swap_in_pages_per_s:.0f})"
            )
            return False, reason, snapshot

        return True, "none", snapshot


# Global default instance
_global_guard: Optional[SystemMemoryGuard] = None


def get_system_memory_guard() -> SystemMemoryGuard:
    global _global_guard
    if _global_guard is None:
        _global_guard = SystemMemoryGuard()
    return _global_guard
