@echo off
rem 启动作业批改系统（使用 conda 环境 ggrade 的 Python）
start cmd /K "D:\DevTools\Miniconda3\envs\ggrade\python.exe .\run.py"
start http://127.0.0.1:5000/
