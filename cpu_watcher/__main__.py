"""cpu_watcher — python -m cpu_watcher 入口。"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cpu_watcher",
        description="实时 simpleperf 函数级 CPU 指令监控 TUI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
    python -m cpu_watcher com.miui.personalassistant
    python -m cpu_watcher com.miui.personalassistant --duration 2 --interval 5
    python -m cpu_watcher 28907 --event cpu-cycles --adb /mnt/d/platform-tools/adb.exe
    python -m cpu_watcher com.miui.personalassistant -d 1 -i 3 --max-entries 100""",
    )
    parser.add_argument("target", help="包名或 PID")
    parser.add_argument(
        "--duration", "-d", type=float, default=1.0,
        help="每次 record 持续时间（秒），默认 1",
    )
    parser.add_argument(
        "--interval", "-i", type=float, default=3.0,
        help="采集周期间隔（秒），默认 3",
    )
    parser.add_argument(
        "--event", "-e", default="instructions",
        help="PMU 事件名，默认 instructions",
    )
    parser.add_argument(
        "--adb", default=None,
        help="adb 可执行路径，例如 /mnt/d/platform-tools/adb.exe",
    )
    parser.add_argument(
        "--max-entries", "-n", type=int, default=50,
        help="最多显示条目数，默认 50",
    )
    args = parser.parse_args()

    # 延迟导入，加快启动速度
    from .collector import SimpleperfCollector, detect_adb
    from .model import CollectorConfig

    adb_bin = detect_adb(args.adb) if args.adb else detect_adb()
    print(f"使用 adb: {adb_bin}", file=sys.stderr)

    config = CollectorConfig(
        target=args.target,
        duration_s=args.duration,
        interval_s=args.interval,
        event=args.event,
        max_entries=args.max_entries,
        adb_bin=adb_bin,
    )
    collector = SimpleperfCollector(config)

    from .app import CpuWatcherApp

    app = CpuWatcherApp(collector=collector, config=config)
    try:
        app.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
