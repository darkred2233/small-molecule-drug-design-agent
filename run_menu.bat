@echo off
chcp 65001 >nul
cd /d "%~dp0.."

:menu
cls
echo ========================================
echo 小分子药物设计Agent - 任务执行
echo ========================================
echo.
echo 请选择要执行的任务：
echo.
echo 1. 验证分子并计算描述符
echo 2. ADMET预测
echo 3. 分子对接
echo 4. 合成可及性评估
echo 5. 运行完整Agent流程
echo 6. 测试API连接
echo 7. 检查工具状态
echo 0. 退出
echo.
set /p choice=请输入选项 (0-7):

if "%choice%"=="1" goto validate
if "%choice%"=="2" goto admet
if "%choice%"=="3" goto docking
if "%choice%"=="4" goto synthesis
if "%choice%"=="5" goto agents
if "%choice%"=="6" goto test_api
if "%choice%"=="7" goto check_tools
if "%choice%"=="0" goto end
echo 无效选项！
pause
goto menu

:validate
echo.
set /p project_id=请输入项目ID:
python scripts\run_tasks.py validate --project %project_id%
pause
goto menu

:admet
echo.
set /p project_id=请输入项目ID:
python scripts\run_tasks.py admet --project %project_id%
pause
goto menu

:docking
echo.
set /p project_id=请输入项目ID:
set /p receptor=请输入受体PDB文件路径:
set /p center_x=结合位点中心X坐标:
set /p center_y=结合位点中心Y坐标:
set /p center_z=结合位点中心Z坐标:
python scripts\run_tasks.py docking --project %project_id% --receptor %receptor% --center %center_x% %center_y% %center_z%
pause
goto menu

:synthesis
echo.
set /p project_id=请输入项目ID:
python scripts\run_tasks.py synthesis --project %project_id%
pause
goto menu

:agents
echo.
set /p project_id=请输入项目ID:
set /p strict=是否使用严格模式？(y/n):
if /i "%strict%"=="y" (
    python scripts\run_tasks.py agents --project %project_id% --strict
) else (
    python scripts\run_tasks.py agents --project %project_id%
)
pause
goto menu

:test_api
echo.
python scripts\test_api.py
pause
goto menu

:check_tools
echo.
python scripts\check_tools.py --verbose
pause
goto menu

:end
echo 再见！
