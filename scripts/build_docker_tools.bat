@echo off
chcp 65001 >nul
cd /d "%~dp0.."

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_docker_tools.ps1" %*
exit /b %errorlevel%
