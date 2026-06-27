import asyncio
import argparse

from .orchestrator import run


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m coordinator",
        description="Coordinator — automated orchestration loop for claude_agents.",
    )
    parser.add_argument(
        "task",
        nargs="?",
        help="Task description. Prompted interactively if omitted.",
    )
    args = parser.parse_args()
    task = args.task or input("Task: ").strip()
    asyncio.run(run(task))


if __name__ == "__main__":
    main()
