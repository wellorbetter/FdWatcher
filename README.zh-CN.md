<div align="right">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">中文</a>
</div>

<div align="center">
  <h1>FdWatcher</h1>
  <p>实时监控 Android 进程文件描述符（fd）分布的终端 TUI 工具，专注于 ashmem 泄漏检测。</p>

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

## 特性

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

## License

[MIT](LICENSE)
