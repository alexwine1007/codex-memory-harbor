#!/usr/bin/env python3
"""兼容入口；实现随 Memory Harbor Skill 一起安装。"""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] /
                     "skills/codex-memory-harbor/scripts/archive_files.py"), run_name="__main__")
