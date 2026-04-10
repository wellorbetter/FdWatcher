# FdWatcher

**[English](./README.md)**

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![平台](https://img.shields.io/badge/平台-Android-green)
![TUI](https://img.shields.io/badge/TUI-textual-purple)
![License](https://img.shields.io/badge/License-MIT-yellow)

实时监控 Android 进程文件描述符（fd）分布的终端 TUI 工具，专注于 **ashmem fd 泄漏检测**。

灵感来自 [csvlens](https://github.com/YS-L/csvlens)。

<!-- 截图占位 — 替换为实际截图/gif -->
<!-- ![demo](docs/demo.gif) -->

---

## 特性

- **实时 fd 分布** — 通过 adb 读取 `/proc/pid/fd`，可配置刷新间隔
- **类型分类** — ashmem / socket / pipe / binder / anon_inode / framework_jars / data_files / system_files / other
- **ashmem 深度分析** — 每次刷新显示 unique inode 数量和最大 dup 数
- **变化量列** — `△刷新间隔`（与上次刷新比）和 `△基线`（与启动初始快照比）
- **光标跟随类型** — 刷新后光标自动定位到同一 fd 类型所在行
- **展开详情面板** — Enter/Space 展开选中行详情；ashmem 显示每个 inode 的 dup 分布
- **信号快捷键** — 一键发送 `kill -42`（monitortrack 开关）或 `kill -39`（fdtrack dump）
- **快照 Dump** — 将原始 `/proc/pid/fd` 列表保存到本地文件
- **自动重连** — 自动等待进程出现/重启，新 PID 时重置基线
- **离线分析** — 传入已有快照文件，无需连接设备

---

## 依赖

| 依赖 | 版本 |
|---|---|
| Python | 3.9+ |
| [textual](https://github.com/Textualize/textual) | >= 8.0 |
| adb | 任意版本 |
| Android 设备 | 需有 `/proc/<pid>/fd` 的 shell/root 访问权限 |

```bash
pip install textual
```

---

## 快速开始

```bash
# 按包名监控
python3 fd_watcher.py com.example.myapp

# 按 PID 监控
python3 fd_watcher.py 1234

# 指定刷新间隔（秒）
python3 fd_watcher.py com.example.myapp -i 2

# 指定 adb 路径（WSL 下使用 Windows adb.exe 时有用）
python3 fd_watcher.py com.example.myapp --adb /mnt/c/platform-tools/adb.exe

# 离线分析已有快照文件
python3 fd_watcher.py fdwatch_dump_1234_20260101_120000.txt
```

---

## 用法

```
usage: fd_watcher.py [-h] [--interval INTERVAL] [--adb ADB] target

位置参数:
  target              包名、PID 或本地快照文件路径

可选参数:
  -h, --help          显示帮助信息
  --interval, -i      刷新间隔（秒），默认 5
  --adb ADB           adb 可执行路径
                      例如 /mnt/c/platform-tools/adb.exe 或 adb.exe
```

---

## 按键说明

| 按键 | 操作 |
|---|---|
| `↑` / `k` | 光标上移 |
| `↓` / `j` | 光标下移 |
| `Enter` / `Space` | 展开/折叠选中类型的 fd 详情 |
| `r` | 立即强制刷新一次 |
| `d` | 将 `/proc/pid/fd` 快照 Dump 到本地文件 |
| `z` | 将 `△基线` 重置为当前快照 |
| `m` | 发送 `kill -42` → 切换 monitortrack 记录开关 |
| `t` | 发送 `kill -39` → fdtrack dump 调用栈到 logcat |
| `?` | 显示帮助浮层 |
| `q` / `Ctrl+C` | 退出 |

---

## 列说明

| 列名 | 说明 |
|---|---|
| 类型 | fd 类型（ashmem / socket / pipe / ...） |
| 数量 | 该类型当前 fd 总数 |
| △5s | 与上次刷新相比的变化（红色=增长，绿色=减少） |
| △初始 | 与启动基线相比的累计变化（`z` 键可重置） |
| 占比 | 该类型占总 fd 的百分比 |
| unique(ashmem) | 仅 ashmem 显示：`N inode, max_dup=M` |

---

## 工作原理

```
adb shell ls -la /proc/<pid>/fd
  → 解析 symlink 目标路径
  → 按类型分类
  → ashmem：按 inode 路径分组 → 统计 unique inode 数与 dup 数
  → 渲染到 textual DataTable
```

**ashmem fd 泄漏特征：**  
正常进程只有少量 ashmem fd。泄漏时通常表现为：
- `ashmem` 数量持续增长（`△初始` 一直增大）
- `unique` inode 数量很少（1~几个），但 `max_dup` 非常大  
  → 同一块共享内存对象被 dup 成了成千上万个 fd

**Java 层可追踪性：**  
`SharedMemory.create()`（Java）→ JNI → `ashmem_create_region()` → `open("/dev/ashmem")` — 该 `open()` 调用经过 bionic libc，**可被 fdtrack/monitortrack hook**。因此 Java 层 ashmem 泄漏完全可通过 `kill -39` / `kill -42` 追踪调用栈。

---

## 离线分析

按 `d` 键后，会在本地保存 `fdwatch_dump_<pid>_<timestamp>.txt` 文件。  
无需连接设备即可事后分析：

```bash
python3 fd_watcher.py fdwatch_dump_1234_20260101_120000.txt
```

输出示例：

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

## 常见问题

**Q：WSL 下提示 `adb: no devices/emulators found`**

显式指定 Windows 侧的 `adb.exe` 路径：

```bash
python3 fd_watcher.py com.example.app --adb /mnt/c/platform-tools/adb.exe
```

或加入 PATH：
```bash
export PATH="/mnt/c/platform-tools:$PATH"
```

---

**Q：读取 `/proc/<pid>/fd` 权限不足**

先以 root 启动 adb：
```bash
adb root
```
或确保目标 App 是 debuggable 版本。

---

**Q：`pm clear` / `am force-stop` 后进程消失了**

FdWatcher 会自动等待并在进程重启后重新连接，新 PID 时自动重置基线。

---

## License

MIT License. 详见 [LICENSE](LICENSE)。
