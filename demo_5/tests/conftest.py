"""pytest 全局配置：把 demo_5/（tests/ 的父目录）加入 sys.path，
使测试可以直接 `import tools` / `import mcp_server`。
"""

import sys
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent.parent
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))
