#!/usr/bin/env python3
import os
import sys
import time


def load_env(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, base_dir)

    env_path = os.getenv("ENV_PATH", os.path.join(base_dir, ".env"))
    load_env(env_path)

    from src.crewai_enterprise.server.task_worker import TaskWorker

    idle_sleep = float(os.getenv("TASK_WORKER_IDLE_SLEEP", "2"))
    worker = TaskWorker()
    while True:
        did_work = worker.run_once()
        if not did_work:
            time.sleep(idle_sleep)


if __name__ == "__main__":
    raise SystemExit(main())
