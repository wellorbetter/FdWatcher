# FdWatcher

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Android-green)
![TUI](https://img.shields.io/badge/TUI-textual-purple)
![License](https://img.shields.io/badge/License-MIT-yellow)

<a href="#english">English</a> | <a href="#中文">中文</a>

![screenshot](docs/screenshot.svg)

---

<a id="english"></a>

## English

Real-time Android fd (file descriptor) monitoring TUI with ashmem leak detection.

### Features

- **Real-time fd distribution** — reads `/proc/<pid>/fd` via adb at configurable intervals
- **Type classification** — ashmem / socket / pipe / binder / anon_inode / framework_jars / data_files / system_files / other
- **ashmem deep analysis** — unique inode count and max dup count per refresh
- **Delta tracking** — `△interval` (vs last refresh) and `△baseline` (vs startup snapshot)
- **Cursor follows type** — highlighted row sticks to the same fd type across refreshes
- **Detail panel** — Enter/Space to expand; ashmem shows per-inode dup distribution
- **Signal shortcuts** — `kill -42` (monitortrack toggle) / `kill -39` (fdtrack dump) in one keypress
- **Dump snapshot** — save raw fd listing to a local file for offline analysis
- **Auto-reconnect** — waits for process restart; resets baseline on new PID

### Requirements

| Dependency | Version |
|---|---|
| Python | 3.9+ |
| [textual](https://github.com/Textualize/textual) | ≥ 0.80 |
| adb | any |
| Android device | shell/root access to `/proc/<pid>/fd` |

```bash
pip install textual
```

### Quick Start

```bash
# Monitor by package name
python3 fd_watcher.py com.example.myapp

# Monitor by PID
python3 fd_watcher.py 1234

# Custom refresh interval (seconds)
python3 fd_watcher.py com.example.myapp -i 2

# Specify adb path (useful on WSL)
python3 fd_watcher.py com.example.myapp --adb /mnt/c/platform-tools/adb.exe

# Offline analysis from a dump file
python3 fd_watcher.py fdwatch_dump_1234_20260101_120000.txt
```

### Usage

```
usage: fd_watcher.py [-h] [--interval INTERVAL] [--adb ADB] target

positional arguments:
  target              Package name, PID, or path to a local snapshot file

options:
  -h, --help          show this help message and exit
  --interval, -i      Refresh interval in seconds (default: 5)
  --adb ADB           Path to adb executable
```

### Key Bindings

| Key | Action |
|---|---|
| `↑` / `k` | Move cursor up |
| `↓` / `j` | Move cursor down |
| `Enter` / `Space` | Expand/collapse detail for selected type |
| `r` | Force refresh |
| `d` | Dump fd snapshot to local file |
| `z` | Reset △baseline to current snapshot |
| `m` | Send `kill -42` → toggle monitortrack |
| `t` | Send `kill -39` → fdtrack dump to logcat |
| `s` | Save SVG screenshot to current directory |
| `?` | Help overlay |
| `q` / `Ctrl+C` | Quit |

### Columns

| Column | Description |
|---|---|
| Type | fd type (ashmem / socket / pipe / …) |
| Count | Current fd count |
| △interval | Change vs last refresh |
| △baseline | Cumulative change vs startup snapshot |
| Ratio | Percentage of total fds |
| unique | ashmem only: `N inode, max_dup=M` |

### How It Works

```
adb shell ls -la /proc/<pid>/fd
  → parse symlink targets
  → classify by type
  → ashmem: group by inode → count unique inodes & dups
  → render in textual DataTable
```

#### ashmem Leak Pattern

A healthy process has a few ashmem fds. A leak typically shows:
- `ashmem` count growing over time (△baseline keeps increasing)
- `unique` inode count stays low but `max_dup` is huge
  → one shared memory object leaked as thousands of dup'd fds

#### Traceability

```
SharedMemory.create() (Java)
  → JNI → ashmem_create_region()
  → open("/dev/ashmem")   ← hooked by fdtrack / monitortrack
```

Java-layer ashmem leaks are traceable via `kill -39` / `kill -42`.

### FAQ

**Q: `adb: no devices/emulators found` on WSL**

```bash
python3 fd_watcher.py com.example.app --adb /mnt/c/platform-tools/adb.exe
```

**Q: Permission denied reading `/proc/<pid>/fd`**

```bash
adb root
```

**Q: Process disappears after force-stop?**

FdWatcher auto-reconnects and resets baseline on new PID.

---

<a id="中文"></a>

## 中文

实时监控 Android 进程文件描述符（fd）分布的终端 TUI 工具，专注于 ashmem fd 泄漏检测。

### 特性

- **实时 fd 分布** — 通过 adb 读取 `/proc/<pid>/fd`，可配置刷新间隔
- **类型分类** — ashmem / socket / pipe / binder / anon_inode / framework_jars / data_files / system_files / other
- **ashmem 深度分析** — 每次刷新显示 unique inode 数量和最大 dup 数
- **变化量列** — `△刷新间隔`（与上次刷新比）和 `△基线`（与启动快照比）
- **光标跟随类型** — 刷新后光标自动定位到同一 fd 类型
- **展开详情** — Enter/Space 展开选中行；ashmem 显示每个 inode 的 dup 分布
- **信号快捷键** — 一键发送 `kill -42`（monitortrack）或 `kill -39`（fdtrack dump）
- **快照导出** — 将 fd 列表保存到本地文件，支持离线分析
- **自动重连** — 进程重启后自动连接，重置基线

### 快速开始

```bash
# 按包名监控
python3 fd_watcher.py com.example.myapp

# 按 PID 监控
python3 fd_watcher.py 1234

# 自定义刷新间隔
python3 fd_watcher.py com.example.myapp -i 2

# 离线分析
python3 fd_watcher.py fdwatch_dump_1234_20260101_120000.txt
```

### ashmem 泄漏特征

- `ashmem` 数量持续增长（△基线持续增大）
- `unique` inode 很少，但 `max_dup` 很大 → 同一共享内存被 dup 成大量 fd

### 可追踪性

`SharedMemory.create()`（Java）→ JNI → `ashmem_create_region()` → `open("/dev/ashmem")`

该调用经过 bionic libc，可被 fdtrack/monitortrack hook，因此 Java 层 ashmem 泄漏可通过 `kill -39` / `kill -42` 追踪调用栈。

## License

[MIT](LICENSE)
