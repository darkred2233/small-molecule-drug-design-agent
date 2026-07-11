"""
Docker工具管理和测试脚本

用于管理和测试Docker部署的计算化学工具：
- Chemprop (ADMET预测)
- GNINA (CNN分子对接)
- AutoDock Vina (分子对接)
- DiffDock (分子对接)
- REINVENT4 (分子生成)
- AutoGrow4 (分子生成)

用法：
    python scripts/manage_docker_tools.py status
    python scripts/manage_docker_tools.py build [tool_name]
    python scripts/manage_docker_tools.py test [tool_name]
    python scripts/manage_docker_tools.py start [tool_name]
    python scripts/manage_docker_tools.py stop [tool_name]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")


TOOLS = {
    "chemprop": {
        "name": "Chemprop",
        "description": "ADMET预测服务",
        "service": "chemprop",
        "image": "chemprop:latest",
        "has_build": True,
        "test_command": ["--version"],
    },
    "gnina": {
        "name": "GNINA",
        "description": "CNN分子对接服务",
        "service": "gnina",
        "image": os.environ.get("GNINA_IMAGE", "gnina/gnina:latest"),
        "has_build": False,
        "test_command": ["--help"],
    },
    "vina": {
        "name": "AutoDock Vina",
        "description": "分子对接服务",
        "service": "vina",
        "image": "vina:latest",
        "has_build": True,
        "test_command": ["-c", "import vina; print('AutoDock Vina installed')"],
    },
    "diffdock": {
        "name": "DiffDock",
        "description": "分子对接服务",
        "service": "diffdock",
        "image": "diffdock:latest",
        "has_build": True,
        "test_command": ["-c", "import diffdock; print('DiffDock installed')"],
    },
    "reinvent4": {
        "name": "REINVENT4",
        "description": "分子生成服务",
        "service": "reinvent4",
        "image": "reinvent4:latest",
        "has_build": True,
        "test_command": ["--help"],
    },
    "autogrow4": {
        "name": "AutoGrow4",
        "description": "分子生成服务",
        "service": "autogrow4",
        "image": "autogrow4:latest",
        "has_build": True,
        "test_command": ["-c", "import autogrow4; print('AutoGrow4 installed')"],
    },
}


def run_command(cmd: list[str], timeout: int = 30, check: bool = False) -> tuple[int, str, str]:
    """运行命令并返回结果"""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except subprocess.CalledProcessError as e:
        return e.returncode, e.stdout or "", e.stderr or ""
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"


def check_docker_available() -> bool:
    """检查Docker是否可用"""
    returncode, stdout, stderr = run_command(["docker", "--version"])
    if returncode == 0:
        print(f"✅ Docker可用: {stdout.strip()}")
        return True
    else:
        print("❌ Docker不可用")
        print(f"   请安装Docker Desktop: https://www.docker.com/products/docker-desktop/")
        return False


def check_docker_compose_available() -> bool:
    """检查Docker Compose是否可用"""
    returncode, stdout, stderr = run_command(["docker", "compose", "version"])
    if returncode == 0:
        print(f"✅ Docker Compose可用: {stdout.strip()}")
        return True
    else:
        print("❌ Docker Compose不可用")
        return False


def check_image_exists(image_name: str) -> bool:
    """检查Docker镜像是否存在"""
    returncode, stdout, stderr = run_command(["docker", "image", "inspect", image_name])
    return returncode == 0


def check_container_running(container_name: str) -> bool:
    """检查容器是否在运行"""
    returncode, stdout, stderr = run_command(
        ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"]
    )
    return container_name in stdout


def get_tool_status(tool_key: str) -> dict:
    """获取工具状态"""
    tool = TOOLS[tool_key]
    service = tool["service"]
    image_name = tool["image"]

    status = {
        "name": tool["name"],
        "service": service,
        "image": image_name,
        "image_exists": check_image_exists(image_name),
        "container_running": check_container_running(service),
    }

    return status


def print_status():
    """打印所有工具的状态"""
    print("=" * 70)
    print("Docker工具状态检查")
    print("=" * 70)

    if not check_docker_available():
        return

    check_docker_compose_available()
    print()

    for tool_key, tool in TOOLS.items():
        status = get_tool_status(tool_key)

        print(f"\n📦 {status['name']} ({tool['description']})")
        print(f"   服务名: {status['service']}")
        print(f"   镜像名: {status['image']}")

        if status["image_exists"]:
            print(f"   ✅ 镜像已构建")
        else:
            action = "docker compose pull" if not tool["has_build"] else "docker compose build"
            print(f"   ❌ 镜像未就绪 (运行: {action} {status['service']})")

        if status["container_running"]:
            print(f"   ✅ 容器运行中")
        else:
            print(f"   ⚪ 容器未运行")

    print("\n" + "=" * 70)
    print("快速命令:")
    print("  准备所有镜像: python scripts\\manage_docker_tools.py build")
    print("  推荐慢网络入口: scripts\\build_tools.bat core")
    print("  启动工具服务: docker compose --profile tools up -d")
    print("  查看运行状态: docker compose ps")
    print("  查看日志: docker compose logs [service_name]")
    print("=" * 70)


def build_tool(tool_key: str = None):
    """构建Docker镜像"""
    print("=" * 70)
    print("构建Docker镜像")
    print("=" * 70)

    if not check_docker_available():
        return 1

    if tool_key:
        if tool_key not in TOOLS:
            print(f"❌ 未知工具: {tool_key}")
            print(f"   可用工具: {', '.join(TOOLS.keys())}")
            return 1

        service = TOOLS[tool_key]["service"]
        docker_action = "pull" if not TOOLS[tool_key]["has_build"] else "build"
        print(f"\n准备 {TOOLS[tool_key]['name']}...")
        returncode, stdout, stderr = run_command(
            ["docker", "compose", docker_action, service],
            timeout=600,
        )

        if returncode == 0:
            print(f"✅ {TOOLS[tool_key]['name']} 准备成功")
        else:
            print(f"❌ {TOOLS[tool_key]['name']} 准备失败")
            print(f"   错误: {stderr}")
            return 1
    else:
        print("\n构建所有工具镜像...")
        pull_services = [
            tool["service"] for tool in TOOLS.values() if not tool["has_build"]
        ]
        build_services = [
            tool["service"] for tool in TOOLS.values() if tool["has_build"]
        ]

        for service in pull_services:
            returncode, stdout, stderr = run_command(
                ["docker", "compose", "pull", service],
                timeout=900,
            )
            if returncode != 0:
                print(f"❌ 拉取 {service} 失败")
                print(f"   错误: {stderr}")
                return 1

        returncode, stdout, stderr = run_command(
            ["docker", "compose", "build"] + build_services,
            timeout=3600,
        )

        if returncode == 0:
            print("✅ 所有工具构建成功")
        else:
            print("❌ 构建失败")
            print(f"   错误: {stderr}")
            return 1

    return 0


def test_tool(tool_key: str):
    """测试Docker工具"""
    if tool_key not in TOOLS:
        print(f"❌ 未知工具: {tool_key}")
        return 1

    tool = TOOLS[tool_key]
    service = tool["service"]

    print("=" * 70)
    print(f"测试 {tool['name']}")
    print("=" * 70)

    # 检查镜像是否存在
    status = get_tool_status(tool_key)
    if not status["image_exists"]:
        print(f"❌ 镜像未构建，请先运行: docker compose build {service}")
        return 1

    # 运行测试命令
    print(f"\n运行测试命令...")
    cmd = ["docker", "compose", "run", "--rm", service] + tool["test_command"]
    returncode, stdout, stderr = run_command(cmd, timeout=60)

    if returncode == 0:
        print(f"✅ {tool['name']} 测试成功")
        print(f"   输出: {stdout.strip()}")
        return 0
    else:
        print(f"❌ {tool['name']} 测试失败")
        print(f"   错误: {stderr}")
        return 1


def test_chemprop_prediction():
    """测试Chemprop ADMET预测"""
    print("\n" + "=" * 70)
    print("测试 Chemprop ADMET预测")
    print("=" * 70)

    # 创建测试输入文件
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_csv = tmpdir_path / "test_input.csv"
        output_csv = tmpdir_path / "test_output.csv"

        # 写入测试SMILES
        test_smiles = [
            "CCO",  # 乙醇
            "CC(=O)Oc1ccccc1C(=O)O",  # 阿司匹林
            "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",  # 咖啡因
        ]

        with open(input_csv, "w") as f:
            f.write("smiles\n")
            for smi in test_smiles:
                f.write(f"{smi}\n")

        print(f"\n测试分子数量: {len(test_smiles)}")
        print(f"输入文件: {input_csv}")

        # 运行Chemprop预测
        cmd = [
            "docker", "compose", "run", "--rm",
            "-v", f"{input_csv}:/data/input.csv",
            "-v", f"{output_csv.parent}:/data/output",
            "chemprop",
            "predict",
            "--test-path", "/data/input.csv",
            "--preds-path", "/data/output/test_output.csv",
        ]

        print(f"\n运行命令: {' '.join(cmd)}")
        returncode, stdout, stderr = run_command(cmd, timeout=120)

        if returncode == 0 and output_csv.exists():
            print("✅ Chemprop预测成功")
            print(f"   输出文件: {output_csv}")

            # 读取结果
            with open(output_csv) as f:
                results = f.read()
            print(f"\n预测结果预览:")
            print(results[:500])
            return 0
        else:
            print("❌ Chemprop预测失败")
            print(f"   返回码: {returncode}")
            print(f"   错误: {stderr}")
            return 1


def start_tool(tool_key: str = None):
    """启动工具服务"""
    if tool_key:
        if tool_key not in TOOLS:
            print(f"❌ 未知工具: {tool_key}")
            return 1

        service = TOOLS[tool_key]["service"]
        print(f"启动 {TOOLS[tool_key]['name']}...")
        returncode, stdout, stderr = run_command(
            ["docker", "compose", "up", "-d", service]
        )
    else:
        print("启动所有工具服务...")
        returncode, stdout, stderr = run_command(
            ["docker", "compose", "--profile", "tools", "up", "-d"]
        )

    if returncode == 0:
        print("✅ 启动成功")
        return 0
    else:
        print("❌ 启动失败")
        print(f"   错误: {stderr}")
        return 1


def stop_tool(tool_key: str = None):
    """停止工具服务"""
    if tool_key:
        if tool_key not in TOOLS:
            print(f"❌ 未知工具: {tool_key}")
            return 1

        service = TOOLS[tool_key]["service"]
        print(f"停止 {TOOLS[tool_key]['name']}...")
        returncode, stdout, stderr = run_command(
            ["docker", "compose", "stop", service]
        )
    else:
        print("停止所有工具服务...")
        returncode, stdout, stderr = run_command(
            ["docker", "compose", "--profile", "tools", "stop"]
        )

    if returncode == 0:
        print("✅ 停止成功")
        return 0
    else:
        print("❌ 停止失败")
        print(f"   错误: {stderr}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="管理和测试Docker计算化学工具"
    )
    parser.add_argument(
        "command",
        choices=["status", "build", "test", "start", "stop", "test-chemprop"],
        help="要执行的命令"
    )
    parser.add_argument(
        "tool",
        nargs="?",
        choices=list(TOOLS.keys()),
        help="工具名称（可选，不指定则操作所有工具）"
    )

    args = parser.parse_args()

    if args.command == "status":
        print_status()
        return 0
    elif args.command == "build":
        return build_tool(args.tool)
    elif args.command == "test":
        if args.tool:
            return test_tool(args.tool)
        else:
            # 测试所有工具
            results = []
            for tool_key in TOOLS.keys():
                result = test_tool(tool_key)
                results.append((tool_key, result))
                print()

            # 汇总
            print("=" * 70)
            print("测试汇总:")
            for tool_key, result in results:
                status = "✅ 通过" if result == 0 else "❌ 失败"
                print(f"  {TOOLS[tool_key]['name']}: {status}")
            print("=" * 70)

            return 0 if all(r == 0 for _, r in results) else 1
    elif args.command == "test-chemprop":
        return test_chemprop_prediction()
    elif args.command == "start":
        return start_tool(args.tool)
    elif args.command == "stop":
        return stop_tool(args.tool)

    return 0


if __name__ == "__main__":
    sys.exit(main())
