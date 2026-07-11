@echo off
echo ========================================
echo 小分子药物设计Agent - 快速启动
echo ========================================
echo.

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: Python未安装
    pause
    exit /b 1
)

echo ✅ Python已安装
echo.

REM 切换到项目目录
cd /d "%~dp0.."

echo ========================================
echo 可用任务
echo ========================================
echo.
echo 1. validate   - 验证分子并计算描述符
echo 2. admet      - ADMET预测
echo 3. docking    - 分子对接
echo 4. synthesis  - 合成可及性评估
echo 5. agents     - 运行完整Agent流程
echo.

echo ========================================
echo 使用示例
echo ========================================
echo.
echo 验证分子:
echo   python scripts\run_tasks.py validate --project PROJ-001
echo.
echo ADMET预测:
echo   python scripts\run_tasks.py admet --project PROJ-001
echo.
echo 分子对接:
echo   python scripts\run_tasks.py docking --project PROJ-001 ^
echo     --receptor receptor.pdb --center 10 20 30
echo.
echo 合成评估:
echo   python scripts\run_tasks.py synthesis --project PROJ-001
echo.
echo 运行Agent:
echo   python scripts\run_tasks.py agents --project PROJ-001
echo.

pause
