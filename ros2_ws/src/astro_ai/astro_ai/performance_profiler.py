#!/usr/bin/env python3
"""ASTRO V1 — Real-Time Performance Profiler for Jetson & ROS 2 Pipeline.

Collects:
  - Jetson CPU usage (%), temperatures (°C), RAM (MB)
  - Jetson GPU usage (%), GPU memory (MB), GPU temperature (°C)
  - Vision Pipeline FPS and Detection counts
  - Audio & AI Latency Metrics (STT ms, TTFT ms, Total Turn ms, p50/p95)
  - Cloud / Local Backend State
"""

import json
import logging

_LOG = logging.getLogger(__name__)

import os
import re
import subprocess
import time
from typing import Any, Dict, Optional


class PerformanceProfiler:
    """Profiles system health, hardware accelerators, and pipeline latencies."""

    def __init__(self):
        self._has_tegrastats = os.path.exists("/usr/bin/tegrastats")
        self._last_cpu_times = None

    def get_hardware_metrics(self) -> Dict[str, Any]:
        metrics = {
            "cpu_usage_pct": 0.0,
            "cpu_temp_c": 0.0,
            "gpu_usage_pct": 0.0,
            "gpu_temp_c": 0.0,
            "gpu_mem_used_mb": 0.0,
            "ram_used_mb": 0.0,
            "ram_total_mb": 0.0,
        }

        # 1. RAM via /proc/meminfo or psutil
        try:
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
            mem_total = 0
            mem_available = 0
            for line in lines:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1]) // 1024
            metrics["ram_total_mb"] = float(mem_total)
            metrics["ram_used_mb"] = float(mem_total - mem_available)
        except Exception as _exc:
            _LOG.debug("get_hardware_metrics: yok sayılan hata (%s)", _exc)

        # 2. CPU Temperature from /sys/class/thermal
        try:
            thermal_dirs = [f"/sys/class/thermal/{d}" for d in os.listdir("/sys/class/thermal") if d.startswith("thermal_zone")]
            temps = []
            for t_dir in thermal_dirs:
                temp_file = os.path.join(t_dir, "temp")
                if os.path.exists(temp_file):
                    with open(temp_file, "r") as f:
                        val = float(f.read().strip())
                        if val > 1000:
                            val /= 1000.0
                        if 0 < val < 120:
                            temps.append(val)
            if temps:
                metrics["cpu_temp_c"] = round(max(temps), 1)
        except Exception as _exc:
            _LOG.debug("get_hardware_metrics: yok sayılan hata (%s)", _exc)

        # 3. Jetson GPU usage via tegrastats or sysfs
        gpu_load_path = "/sys/devices/gpu.0/load"
        if os.path.exists(gpu_load_path):
            try:
                with open(gpu_load_path, "r") as f:
                    val = float(f.read().strip()) / 10.0  # 0-1000 -> 0-100%
                    metrics["gpu_usage_pct"] = round(val, 1)
            except Exception as _exc:
                _LOG.debug("get_hardware_metrics: yok sayılan hata (%s)", _exc)

        # 4. CPU usage via /proc/stat
        try:
            with open("/proc/stat", "r") as f:
                cpu_line = f.readline().split()[1:]
            cpu_times = [float(x) for x in cpu_line]
            if self._last_cpu_times:
                diff = [c - p for c, p in zip(cpu_times, self._last_cpu_times)]
                total_diff = sum(diff)
                idle_diff = diff[3]
                if total_diff > 0:
                    metrics["cpu_usage_pct"] = round(100.0 * (1.0 - idle_diff / total_diff), 1)
            self._last_cpu_times = cpu_times
        except Exception as _exc:
            _LOG.debug("get_hardware_metrics: yok sayılan hata (%s)", _exc)

        return metrics

    def generate_diagnostic_report(
        self,
        latency_stats: Dict[str, Any],
        cloud_status: Dict[str, Any],
        active_persona: str,
        fsm_state: str,
    ) -> Dict[str, Any]:
        hw = self.get_hardware_metrics()
        return {
            "timestamp": time.time(),
            "hardware": hw,
            "latency": latency_stats,
            "cloud_status": cloud_status,
            "robot_state": {
                "persona": active_persona,
                "fsm": fsm_state,
            }
        }
