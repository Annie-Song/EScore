@echo off
rem 启动作业批改系统（使用 conda 环境 ggrade 的 Python）
rem 向量嵌入与 OCR 均为独立微服务，先启动两个服务再启动主应用
start cmd /K "D:\DevTools\Miniconda3\envs\ggrade\python.exe -m servers.embedding.server"
start cmd /K "D:\DevTools\Miniconda3\envs\ggrade\python.exe -m servers.ocr.server"
start cmd /K "D:\DevTools\Miniconda3\envs\ggrade\python.exe .\run.py"

rem 等待三服务就绪（最多 30 秒），失败则明确报错且不开浏览器
"D:\DevTools\Miniconda3\envs\ggrade\python.exe" scripts\healthcheck.py --wait 30
if errorlevel 1 (
    echo 服务启动失败，请查看对应终端日志
    exit /b 1
)
echo 三服务已就绪，正在打开浏览器...
start http://127.0.0.1:5000/
