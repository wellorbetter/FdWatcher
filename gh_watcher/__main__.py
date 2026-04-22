"""gh_watcher — python -m gh_watcher 入口。"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gh_watcher",
        description="GitHub 聚合活动看板 TUI — 查看你参与的 Issues / PRs / Notifications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
    python -m gh_watcher
    python -m gh_watcher --repos user/repo1,org/repo2
    python -m gh_watcher --interval 120 --limit 50
    python -m gh_watcher --gh /usr/local/bin/gh --include-closed""",
    )
    parser.add_argument(
        "--repos", "-R", default="",
        help="额外关注的 repos，逗号分隔 (如 owner/repo1,org/repo2)",
    )
    parser.add_argument(
        "--interval", "-i", type=float, default=60.0,
        help="自动刷新间隔（秒），默认 60",
    )
    parser.add_argument(
        "--limit", "-n", type=int, default=30,
        help="每类最多条目数，默认 30",
    )
    parser.add_argument(
        "--gh", default=None,
        help="gh CLI 可执行路径",
    )
    parser.add_argument(
        "--include-closed", action="store_true",
        help="包含已关闭的 issues/PRs",
    )
    parser.add_argument(
        "--user", "-u", default="",
        help="GitHub 用户名（默认自动检测）",
    )
    args = parser.parse_args()

    from .collector import GhCollector, detect_gh
    from .model import CollectorConfig

    try:
        gh_bin = detect_gh(args.gh)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    extra_repos = tuple(
        r.strip() for r in args.repos.split(",") if r.strip()
    )

    config = CollectorConfig(
        username=args.user,
        extra_repos=extra_repos,
        interval_s=args.interval,
        limit=args.limit,
        gh_bin=gh_bin,
        include_closed=args.include_closed,
    )
    collector = GhCollector(config)

    from .app import GhWatcherApp

    app = GhWatcherApp(collector=collector, config=config)
    try:
        app.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
