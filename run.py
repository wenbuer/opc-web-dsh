# -*- coding: utf-8 -*-
"""免安装启动入口：python run.py → http://127.0.0.1:8901

等价于安装后运行 python -m opc_web 或 opc-web 命令。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from opc_web.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
