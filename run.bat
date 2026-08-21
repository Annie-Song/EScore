@echo off
rem 启动作业批改系统（使用 conda 环境 ggrade 的 Python）
rem 向量嵌入与 OCR 均为独立微服务，先启动两个服务再启动主应用
start cmd /K "D:\DevTools\Miniconda3\envs\ggrade\python.exe -m services.embedding_server"
start cmd /K "D:\DevTools\Miniconda3\envs\ggrade\python.exe -m services.ocr_server"
start cmd /K "D:\DevTools\Miniconda3\envs\ggrade\python.exe .\run.py"
start http://127.0.0.1:5000/
