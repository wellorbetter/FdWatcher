#!/usr/bin/env python3
"""cpu_watcher.py — 实时 simpleperf 函数级 CPU 指令监控 TUI

用法:
    python3 cpu_watcher.py <package_or_pid> [--duration 1] [--interval 3]
    python3 cpu_watcher.py com.miui.personalassistant
    python3 cpu_watcher.py com.miui.personalassistant -d 2 -i 5 --adb adb.exe
"""
from cpu_watcher.__main__ import main

if __name__ == "__main__":
    main()
