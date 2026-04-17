"""SimpleperfCollector — 通过 adb 执行 simpleperf 采集并解析结果。"""

from __future__ import annotations

import math
import os
import shutil
import subprocess

from .model import CollectorConfig, PerfSnapshot
from .parser import parse_simpleperf_csv

_WSL_ADB_CANDIDATES = [
    "/mnt/c/platform-tools/adb.exe",
    "/mnt/d/platform-tools/adb.exe",
    "/mnt/d/Sdk/platform-tools/adb.exe",
    "/mnt/c/Sdk/platform-tools/adb.exe",
    "/mnt/c/Users/{}/AppData/Local/Android/Sdk/platform-tools/adb.exe",
    "/mnt/d/Users/{}/AppData/Local/Android/Sdk/platform-tools/adb.exe",
]


def detect_adb(adb_hint: str = "adb") -> str:
    if adb_hint != "adb" and (shutil.which(adb_hint) or os.path.isfile(adb_hint)):
        return adb_hint
    # WSL 下 adb.exe 通过 Windows PATH 暴露，优先于 Linux 的 adb
    adb_exe = shutil.which("adb.exe")
    if adb_exe:
        return adb_exe
    if shutil.which("adb"):
        return "adb"
    for candidate in _WSL_ADB_CANDIDATES:
        if "{" in candidate:
            try:
                candidate = candidate.format(os.environ.get("USER", ""))
            except Exception:
                continue
        if os.path.isfile(candidate):
            return candidate
    return "adb"


def adb_shell(cmd: str, adb_bin: str = "adb", timeout: int = 10) -> str:
    try:
        result = subprocess.run(
            [adb_bin, "shell", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def check_adb(adb_bin: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            [adb_bin, "devices"], capture_output=True, text=True, timeout=5,
        )
        lines = [
            l for l in r.stdout.splitlines()
            if l.strip() and "List of devices" not in l
        ]
        if not lines:
            return False, f"adb ({adb_bin}) 未找到连接的设备"
        if all("offline" in l for l in lines):
            return False, f"设备离线: {lines[0]}"
        return True, lines[0].split()[0]
    except FileNotFoundError:
        return False, f"找不到 adb: {adb_bin}"


def resolve_pid(target: str, adb_bin: str) -> str | None:
    if target.isdigit():
        return target
    out = adb_shell(f"pidof {target}", adb_bin=adb_bin)
    pids = out.strip().split()
    return pids[0] if pids else None


class SimpleperfCollector:
    def __init__(self, config: CollectorConfig) -> None:
        self._config = config

    def collect(self) -> PerfSnapshot | None:
        cfg = self._config
        pid = resolve_pid(cfg.target, cfg.adb_bin)
        if not pid:
            return None

        data_path = f"{cfg.device_tmp}/cpu_perf_{pid}.data"
        record_timeout = math.ceil(cfg.duration_s) + 10

        # --app 模式在 SELinux Enforcing 下有权限，-p 模式通常被拒
        # -g 记录调用栈，配合 report --children 归因到 Java 业务层
        use_app = not cfg.target.isdigit()
        if use_app:
            record_cmd = (
                f"simpleperf record --app {cfg.target} "
                f"--duration {cfg.duration_s} -e {cfg.event} -g -o {data_path}"
            )
        else:
            record_cmd = (
                f"simpleperf record -p {pid} "
                f"--duration {cfg.duration_s} -e {cfg.event} -g -o {data_path}"
            )

        try:
            adb_shell(record_cmd, adb_bin=cfg.adb_bin, timeout=record_timeout)

            report_output = adb_shell(
                f"simpleperf report -i {data_path} "
                f"--csv --sort dso,symbol -n --print-event-count --children",
                adb_bin=cfg.adb_bin,
                timeout=15,
            )

            snapshot = parse_simpleperf_csv(report_output, max_entries=cfg.max_entries)
        finally:
            adb_shell(f"rm -f {data_path}", adb_bin=cfg.adb_bin, timeout=5)

        if snapshot is None:
            return None

        return PerfSnapshot(
            timestamp=snapshot.timestamp,
            pid=pid,
            total_events=snapshot.total_events,
            total_samples=snapshot.total_samples,
            event_name=snapshot.event_name,
            duration_ms=int(cfg.duration_s * 1000),
            entries=snapshot.entries,
        )

    def check_ready(self) -> tuple[bool, str]:
        ok, msg = check_adb(self._config.adb_bin)
        if not ok:
            return False, msg

        which_out = adb_shell(
            "which simpleperf", adb_bin=self._config.adb_bin, timeout=5,
        )
        if not which_out.strip():
            return False, "设备上未找到 simpleperf"

        return True, msg

    def get_target_display(self) -> str:
        return self._config.target
