<div align="right">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">中文</a>
</div>

<div align="center">
  <h1>Android Perf TUI Toolkit</h1>
  <p>Android 性能诊断 TUI 工具集 — fd 泄漏检测 + CPU 指令级性能分析。</p>

  <p>
    <img alt="Python" src="https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white">
    <img alt="Platform" src="https://img.shields.io/badge/Platform-Android-3DDC84?logo=android&logoColor=white">
    <img alt="TUI" src="https://img.shields.io/badge/TUI-textual-7B2FBE">
    <img alt="License" src="https://img.shields.io/badge/License-MIT-yellow">
  </p>
</div>

<div align="center">
  <img src="docs/screenshot.svg" width="720" alt="FdWatcher 截图">
</div>

---

## 工具列表

| 工具 | 说明 |
|---|---|
| **[fd_watcher](#fd_watcher)** | 实时 fd 分布监控 — 检测 ashmem 泄漏 |
| **[cpu_watcher](#cpu_watcher)** | 实时函数级 CPU 指令分析 — 基于 simpleperf |

---

## fd_watcher

### 特性

| | |
|---|---|
| **实时 fd 分布** | 通过 adb 读取 `/proc/<pid>/fd`，可配置刷新间隔 |
| **类型分类** | ashmem / socket / pipe / binder / anon_inode / framework_jars / data_files / system_files / other |
| **ashmem 深度分析** | 每次刷新显示 unique inode 数量和最大 dup 数 |
| **变化量列** | `△interval`（与上次刷新比）和 `△baseline`（与启动快照比） |
| **光标跟随类型** | 刷新后光标自动定位到同一 fd 类型 |
| **展开详情** | Enter/Space 展开选中行；ashmem 显示每个 inode 的 dup 分布 |
| **信号快捷键** | 一键发送 `kill -42`（monitortrack）或 `kill -39`（fdtrack dump） |
| **快照导出** | 将 fd 列表保存到本地文件，支持离线分析 |
| **自动重连** | 进程重启后自动连接，重置基线 |

---

## 环境要求

| 依赖 | 版本 |
|---|---|
| Python | 3.9+ |
| [textual](https://github.com/Textualize/textual) | ≥ 0.80 |
| adb | 任意版本 |
| Android 设备 | 需要 shell/root 权限访问 `/proc/<pid>/fd` |

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

# 自定义刷新间隔（秒）
python3 fd_watcher.py com.example.myapp -i 2

# 指定 adb 路径（WSL 用户常用）
python3 fd_watcher.py com.example.myapp --adb /mnt/c/platform-tools/adb.exe

# 离线分析 dump 文件
python3 fd_watcher.py fdwatch_dump_1234_20260101_120000.txt
```

### 命令行参数

```
usage: fd_watcher.py [-h] [--interval INTERVAL] [--adb ADB] target

positional arguments:
  target              包名、PID 或本地快照文件路径

options:
  -h, --help          显示帮助信息
  --interval, -i      刷新间隔，单位秒（默认：5）
  --adb ADB           adb 可执行文件路径
```

---

## 快捷键

| 按键 | 功能 |
|---|---|
| `↑` / `k` | 向上移动光标 |
| `↓` / `j` | 向下移动光标 |
| `Enter` / `Space` | 展开 / 收起选中行详情 |
| `r` | 强制刷新 |
| `d` | 导出 fd 快照到本地文件 |
| `z` | 将 △baseline 重置为当前快照 |
| `m` | 发送 `kill -42` → 切换 monitortrack |
| `t` | 发送 `kill -39` → fdtrack dump 到 logcat |
| `s` | 保存 SVG 截图 |
| `?` | 帮助面板 |
| `q` / `Ctrl+C` | 退出 |

---

## 列说明

| 列名 | 说明 |
|---|---|
| Type | fd 类型（ashmem / socket / pipe / …） |
| Count | 当前 fd 数量 |
| △interval | 与上次刷新的变化量 |
| △baseline | 与启动快照的累计变化量 |
| Ratio | 占总 fd 的百分比 |
| unique | 仅 ashmem — `N inode, max_dup=M` |

---

## 工作原理

```
adb shell ls -la /proc/<pid>/fd
  → 解析符号链接目标
  → 按类型分类
  → ashmem：按 inode 分组 → 统计 unique inode 数及 dup 数
  → 渲染到 textual DataTable
```

### 识别 ashmem 泄漏

健康进程的 ashmem 数量应保持稳定。泄漏的典型特征：

- `ashmem` 数量持续增长 — **△baseline 不断增大**
- `unique` inode 数很少，但 **`max_dup` 很大**
  → 同一共享内存对象被 dup 成大量 fd

### 可追踪性

```
SharedMemory.create()（Java）
  → JNI → ashmem_create_region()
  → open("/dev/ashmem")   ← 被 fdtrack / monitortrack hook
```

Java 层 ashmem 泄漏可通过 `kill -39` / `kill -42` 追踪调用栈。

---

## 常见问题

**WSL 下 `adb: no devices/emulators found`**

```bash
python3 fd_watcher.py com.example.app --adb /mnt/c/platform-tools/adb.exe
```

**读取 `/proc/<pid>/fd` 权限被拒绝**

```bash
adb root
```

**强制停止进程后消失了？**

FdWatcher 会自动重连，并在新 PID 上重置 △baseline。

---

## cpu_watcher

基于 `simpleperf` 的实时函数级 CPU 指令分析工具。周期性执行 `simpleperf record` + `simpleperf report`，在 TUI 中展示函数级指令数排名及变化趋势。

### 特性

| | |
|---|---|
| **函数级分析** | 按指令数排名展示每个函数的 CPU 开销 |
| **变化追踪** | `Δ/prev`（与上次比）和 `Δ/baseline`（与启动时比） |
| **搜索过滤** | `/` 键按函数名或模块名过滤 |
| **暂停/继续** | `p` 键冻结画面，方便分析 |
| **火焰图导出** | `f` 键导出折叠栈格式，可用 flamegraph.pl 生成火焰图 |
| **快照导出** | `d` 键保存当前分析结果到文本文件 |
| **自动探测 adb** | WSL 环境自动查找 `adb.exe` |
| **可配置采样** | `--duration` 和 `--interval` 控制采样行为 |

### 快速开始

```bash
# 按包名监控
python3 cpu_watcher.py com.example.myapp

# 自定义采样：2 秒采集，5 秒间隔
python3 cpu_watcher.py com.example.myapp -d 2 -i 5

# 按 PID 监控，指定 adb 路径
python3 cpu_watcher.py 28907 --adb /mnt/d/Sdk/platform-tools/adb.exe

# 使用 cpu-cycles 事件
python3 cpu_watcher.py com.example.myapp -e cpu-cycles:u

# 也可以作为模块运行
python3 -m cpu_watcher com.example.myapp
```

### 命令行参数

```
usage: cpu_watcher [-h] [--duration DURATION] [--interval INTERVAL]
                   [--event EVENT] [--adb ADB] [--max-entries MAX_ENTRIES]
                   target

positional arguments:
  target                包名或 PID

options:
  --duration, -d        每次 record 持续时间，单位秒（默认：1）
  --interval, -i        采集周期间隔，单位秒（默认：3）
  --event, -e           PMU 事件名（默认：instructions:u）
  --adb ADB             adb 可执行文件路径（自动探测）
  --max-entries, -n     最多显示条目数（默认：50）
```

### 快捷键

| 按键 | 功能 |
|---|---|
| `↑` / `↓` | 上下移动光标 |
| `p` | 暂停 / 继续采集 |
| `r` | 立即刷新 |
| `z` | 重置 Δ/baseline 基线 |
| `/` | 搜索过滤函数名或模块名 |
| `Esc` | 关闭搜索 |
| `d` | 导出快照到文件 |
| `f` | 导出火焰图数据 |
| `s` | 保存 SVG 截图 |
| `?` | 帮助面板 |
| `q` | 退出 |

### 列说明

| 列名 | 说明 |
|---|---|
| # | 按指令数排名 |
| 占比% | 占总事件百分比 |
| 指令数 | 该函数的事件计数 |
| Δ/prev | 与上次采集的变化 |
| Δ/base | 与基线的累计变化 |
| 模块 | 共享库 / DSO 名称 |
| 函数 | 符号名（过长会截断） |

### 工作原理

```
simpleperf record --app <包名> --duration N -e instructions:u
  → simpleperf report --csv --sort dso,symbol
  → 解析 CSV 输出
  → 计算 delta（短期 + 长期）
  → 渲染到 Textual DataTable
```

### 环境要求

- Android 设备需要有 `simpleperf`（userdebug/eng 版本或 NDK simpleperf）
- adb 连接
- `--app` 模式（默认）：目标应用需为 debuggable
- `-p` 模式（PID）：可能需要 root，取决于 SELinux 策略

---

## License

[MIT](LICENSE)
