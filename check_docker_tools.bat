@echo off
echo ============================================================
echo 检查Docker工具镜像状态
echo ============================================================
echo.

echo 检查Docker是否运行...
docker ps >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Docker未运行或未安装
    echo 请启动Docker Desktop
    exit /b 1
)
echo ✅ Docker正在运行
echo.

echo ============================================================
echo 已构建的工具镜像:
echo ============================================================
docker images --filter "reference=chemprop*" --filter "reference=diffdock*" --filter "reference=reinvent4*" --filter "reference=autogrow4*" --filter "reference=vina*" --filter "reference=gnina*" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"
echo.

echo ============================================================
echo 详细镜像列表:
echo ============================================================
echo.

docker image inspect chemprop:latest >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ✅ chemprop:latest - 已构建
) else (
    echo ❌ chemprop:latest - 未构建
)

docker image inspect diffdock:latest >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ✅ diffdock:latest - 已构建
) else (
    echo ❌ diffdock:latest - 未构建
)

docker image inspect reinvent4:latest >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ✅ reinvent4:latest - 已构建
) else (
    echo ❌ reinvent4:latest - 未构建
)

docker image inspect autogrow4:latest >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ✅ autogrow4:latest - 已构建
) else (
    echo ❌ autogrow4:latest - 未构建
)

docker image inspect vina:latest >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ✅ vina:latest - 已构建
) else (
    echo ❌ vina:latest - 未构建
)

docker image inspect gnina/gnina:latest >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ✅ gnina/gnina:latest - 已下载
) else (
    echo ❌ gnina/gnina:latest - 未下载
)

echo.
echo ============================================================
echo 检查完成
echo ============================================================
echo.
echo 如果镜像未构建，运行: setup_and_build.bat
echo 或单独构建: docker-compose build chemprop
