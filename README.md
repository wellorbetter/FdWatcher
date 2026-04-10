# FdWatcher

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Android-green)
![TUI](https://img.shields.io/badge/TUI-textual-purple)
![License](https://img.shields.io/badge/License-MIT-yellow)

A terminal TUI tool for real-time monitoring of Android process file descriptor (fd) distribution, with a focus on **ashmem fd leak detection**.

Inspired by [csvlens](https://github.com/YS-L/csvlens).

---

实时监控 Android 进程文件描述符（fd）分布的终端 TUI 工具，专注于 **ashmem fd 泄漏检测**。

灵感来自 [csvlens](https://github.com/YS-L/csvlens)。

---

<!-- screenshot placeholder — replace with actual screenshot/gif -->
<!-- ![demo](docs/demo.gif) -->

---

## Features / 特性

- **Real-time fd distribution** — reads `/proc/pid/fd` via adb, refreshed at configurable intervals
- **Type classification** — ashmem / socket / pipe / binder / anon_inode / framework_jars / data_files / system_files / other
- **ashmem deep analysis** — shows unique inode count and max dup count per refresh
- **Delta columns** — `△interval` (vs last refresh) and `△baseline` (vs startup snapshot)
- **Cursor follows type** — the highlighted row sticks to the same fd type across refreshes
- **Expand detail panel** — press Enter/Space on any row to see target breakdown; ashmem shows per-inode dup distribution
- **Signal shortcuts** — send `kill -42` (monitortrack toggle) or `kill -39` (fdtrack dump) in one keypress
- **Dump snapshot** — save raw `/proc/pid/fd` listing to a local file
- **Auto-reconnect** — waits for the process to appear/restart; resets baseline on new PID
- **Offline analysis** — pass a previously dumped file instead of a live device

---

- **实时 fd 分布** — 通过 adb 读取 `/proc/pid/fd`，可配置刷新间隔
- **类型分类** — ashmem / socket / pipe / binder / anon_inode / framework_jars / data_files / system_files / other
- **ashmem 深度分析** — 每次刷新显示 unique inode 数量和最大 dup 数
- **变化量列** — `△刷新间隔`（与上次刷新比）和 `△基线`（与启动初始快照比）
- **光标跟随类型** — 刷新后光标自动定位到同一 fd 类型所在行
- **展开详情面板** — Enter/Space 展开选中行详情；ashmem 显示每个 inode 的 dup 分布
- **信号快捷键** — 一键发送 `kill -42`（monitortrack 开关）或 `kill -39`（fdtrack dump）
- **快照 Dump** — 将原始 `/proc/pid/fd` 列表保存到本地文件
- **自动重连** — 自动等待进程出现/重启，新 PID 时重置基线
- **离线分析** — 传入已有的快照文件，无需连接设备

---

## Requirements / 依赖

| Requirement | Version |
|---|---|
| Python | 3.9+ |
| [textual](https://github.com/Textualize/textual) | >= 8.0 |
| adb | any |
| Android device | shell/root access to `/proc/<pid>/fd` |

```bash
pip install textual
```

---

## Quick Start / 快速开始

```bash
# Monitor by package name
python3 fd_watcher.py com.example.myapp

# Monitor by PID
python3 fd_watcher.py 1234

# Specify refresh interval (seconds)
python3 fd_watcher.py com.example.myapp -i 2

# Specify adb path (useful on WSL with Windows adb.exe)
python3 fd_watcher.py com.example.myapp --adb /mnt/c/platform-tools/adb.exe

# Offline analysis of a previously dumped file
python3 fd_watcher.py fdwatch_dump_1234_20260101_120000.txt
```

---

## Usage / 用法

```
usage: fd_watcher.py [-h] [--interval INTERVAL] [--adb ADB] target

positional arguments:
  target              Package name, PID, or path to a local snapshot file

options:
  -h, --help          show this help message and exit
  --interval, -i      Refresh interval in seconds (default: 5)
  --adb ADB           Path to adb executable
                      e.g. /mnt/d/platform-tools/adb.exe  or  adb.exe
```

---

## Key Bindings / 按键说明

| Key | Action |
|---|---|
| `↑` / `k` | Move cursor up |
| `↓` / `j` | Move cursor down |
| `Enter` / `Space` | Expand/collapse fd detail for selected type |
| `r` | Force refresh immediately |
| `d` | Dump `/proc/pid/fd` snapshot to a local file |
| `z` | Reset `△baseline` to current snapshot |
| `m` | Send `kill -42` → toggle monitortrack recording |
| `t` | Send `kill -39` → fdtrack dump callstacks to logcat |
| `?` | Show help overlay |
| `q` / `Ctrl+C` | Quit |

---

## Column Explanation / 列说明

| Column | Description |
|---|---|
| 类型 | fd type (ashmem / socket / pipe / ...) |
| 数量 | Current fd count for this type |
| △5s | Change vs last refresh (red = growing, green = shrinking) |
| △初始 | Cumulative change vs startup baseline (`z` to reset) |
| 占比 | Percentage of total fds |
| unique(ashmem) | ashmem only: `N inode, max_dup=M` |

---

## How It Works / 原理

```
adb shell ls -la /proc/<pid>/fd
  → parse symlink targets
  → classify by type
  → ashmem: group by inode path → count unique inodes & dups
  → render in textual DataTable
```

**ashmem fd leak pattern:**
A healthy process may have a few ashmem fds. A leak typically shows:
- `ashmem` count growing over time (`△初始` keeps increasing)
- `unique` inode count stays low (1–few) but `max_dup` is huge
  → one logical shared memory object leaked as thousands of dup fds

**Java layer traceability:**
`SharedMemory.create()` (Java) → JNI → `ashmem_create_region()` → `open("/dev/ashmem")` — this `open()` call goes through bionic libc and **is hooked by fdtrack/monitortrack**. So Java-layer ashmem leaks are traceable with `kill -39` / `kill -42`.

---

**ashmem fd 泄漏特征：**
- `ashmem` 数量随时间增长（`△初始` 持续增大）
- `unique` inode 数量很少（1~几个），但 `max_dup` 很大
  → 同一块共享内存对象被 dup 成了成千上万个 fd

**Java 层可追踪性：**
`SharedMemory.create()`（Java）→ JNI → `ashmem_create_region()` → `open("/dev/ashmem")` — 该 `open()` 调用经过 bionic libc，**可被 fdtrack/monitortrack hook**。因此 Java 层 ashmem 泄漏可通过 `kill -39` / `kill -42` 追踪调用栈。

---

## Offline Analysis / 离线分析

When you dump a snapshot with `d`, a file like `fdwatch_dump_<pid>_<timestamp>.txt` is saved.
You can analyze it later without a connected device:

```bash
python3 fd_watcher.py fdwatch_dump_1234_20260101_120000.txt
```

Output example:

```
════════════════════════════════════════════════════════════
  FD Snapshot Analysis: fdwatch_dump_1234_20260101_120000.txt
  Total FDs: 3200
════════════════════════════════════════════════════════════
类型                              数量    占比
────────────────────────────────────────────────────────────
  ashmem                          2980   93.1% ◀ LEAK?
  socket                            92    2.9%
  pipe                              48    1.5%
  ...
```

---

## FAQ

**Q: `adb: no devices/emulators found` on WSL**

Pass the Windows `adb.exe` path explicitly:

```bash
python3 fd_watcher.py com.example.app --adb /mnt/c/platform-tools/adb.exe
```

Or set it in your shell:
```bash
export PATH="/mnt/c/platform-tools:$PATH"
```

---

**Q: Permission denied reading `/proc/<pid>/fd`**

Run adb as root first:
```bash
adb root
```
Or the target app must be debuggable.

---

**Q: Process disappears after `adb shell am force-stop` / `pm clear`**

FdWatcher automatically waits and reconnects when the process restarts.
The baseline is reset on the new PID.

---

## License

MIT License. See [LICENSE](LICENSE).
