@echo off
echo ========================================
echo 配置Docker中国镜像源
echo ========================================
echo.
echo 1. 打开Docker Desktop
echo 2. 点击右上角设置图标 (齿轮)
echo 3. 选择 Docker Engine
echo 4. 在配置中添加以下内容:
echo.
echo {
echo   "registry-mirrors": [
echo     "https://docker.mirrors.ustc.edu.cn",
echo     "https://hub-mirror.c.163.com",
echo     "https://mirror.ccs.tencentyun.com"
echo   ]
echo }
echo.
echo 5. 点击 Apply ^& Restart
echo 6. 等待Docker重启完成
echo.
echo 配置文件已保存到: docker\daemon.json
echo 你可以复制这个文件的内容到Docker设置中
echo.
pause

echo.
echo ========================================
echo 现在开始构建Docker工具
echo ========================================
echo.
cd /d "%~dp0.."
call scripts\build_tools.bat
