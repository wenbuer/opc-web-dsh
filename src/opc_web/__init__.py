# -*- coding: utf-8 -*-
"""opc_web —— OPC 控制台（opc-web）后端包。

职责边界（R1 维护 · R0 拍板不变）：
  1. 只读知识库全部 .md（文件树/单文件/待决清单/每日简报）
  2. 状态写入集中在 store.py（SQLite 台账，单写者）；md 侧唯一写操作是
     R0 在页面提交批阅 → 写入《批阅台/批阅台.md》对应待决的「R0 批阅」栏
  3. 不替 R0 拍板；角色派发由常驻主会话 R1 用 DSH subagent 执行

启动：python run.py 或 python -m opc_web（端口取自 opc-config.json，默认 8901）
目录约定：单根目录（配置 root / env OPC_KB_ROOT 覆盖）→ 自动生成 批阅台/、工作区/（按角色名称）、知识库/。
"""
__version__ = "1.15.0"
