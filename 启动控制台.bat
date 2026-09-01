@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   OPC 智能体工作台（opc-web）正在启动 ...
echo   地址: 见下方启动日志（端口取自 opc-config.json，默认 8901）
echo   说明: 首次启动自动生成 批阅台/ 工作区/ 知识库/ 三目录（运行数据不入库）
echo ============================================
rem 浏览器由 run.py 打开，端口才跟得上配置
python run.py
pause
