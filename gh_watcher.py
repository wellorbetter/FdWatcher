#!/usr/bin/env python3
"""gh_watcher.py — GitHub 聚合活动看板 TUI

用法:
    python3 gh_watcher.py
    python3 gh_watcher.py --repos user/repo1,org/repo2
    python3 gh_watcher.py --interval 120 --limit 50
"""
from gh_watcher.__main__ import main

if __name__ == "__main__":
    main()
