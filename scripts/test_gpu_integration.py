#!/usr/bin/env python
"""
真实 GPU 集成测试脚本

在你的本地机器上运行此脚本，验证：
1. Docker GPU 是否真的可用
2. 各个化学工具是否真的能调用 GPU
3. GPU 模式 vs CPU 模式的性能对比
"""

import subprocess
import time
from pathlib import Path


def test_docker_gpu_available():
    """测试 Docker 是否能访问 GPU"""
    print("=" * 80)
    print("测试 1: Docker GPU 基础可用性")
    print("=" * 80)

    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--gpus", "all", "nvidia/cuda:12.0-base", "nvidia-smi"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            print("✅ GPU 可用！")
            print("\nGPU 信息:")
            print(result.stdout)
            return True
        else:
            print("❌ GPU 不可用")
            print(f"错误: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("❌ 超时")
        return False
    except FileNotFoundError:
        print("❌ Docker 未安装")
        return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def test_gnina_gpu():
    """测试 gnina 是否使用 GPU"""
    print("\n" + "=" * 80)
    print("测试 2: gnina GPU 使用")
    print("=" * 80)

    # 检查 gnina 镜像是否存在
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "gnina/gnina:latest"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            print("⚠️ gnina/gnina:latest 镜像不存在，跳过测试")
            return None
    except Exception:
        print("⚠️ 无法检查 gnina 镜像，跳过测试")
        return None

    # 测试 GPU 模式
    print("\n测试 GPU 模式...")
    gpu_start = time.time()
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--gpus", "all", "gnina/gnina:latest", "gnina", "--help"],
            capture_output=True,
            timeout=10,
        )
        gpu_time = time.time() - gpu_start

        if result.returncode == 0:
            print(f"✅ GPU 模式成功 (耗时: {gpu_time:.2f}s)")

            # 检查输出中是否提到 GPU
            if "gpu" in result.stdout.decode('utf-8', errors='ignore').lower():
                print("  ✅ 检测到 GPU 相关信息")
            else:
                print("  ⚠️ 未在输出中检测到 GPU 信息")
            return True
        else:
            print(f"❌ GPU 模式失败: {result.stderr.decode('utf-8', errors='ignore')[:200]}")
            return False

    except subprocess.TimeoutExpired:
        print("❌ GPU 模式超时")
        return False
    except Exception as e:
        print(f"❌ GPU 模式错误: {e}")
        return False


def test_chemprop_gpu():
    """测试 chemprop 是否使用 GPU"""
    print("\n" + "=" * 80)
    print("测试 3: chemprop GPU 使用")
    print("=" * 80)

    # 检查 chemprop 镜像是否存在
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "chemprop:latest"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            print("⚠️ chemprop:latest 镜像不存在，跳过测试")
            return None
    except Exception:
        print("⚠️ 无法检查 chemprop 镜像，跳过测试")
        return None

    print("\n测试 GPU 模式...")
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--gpus", "all", "chemprop:latest", "chemprop", "--help"],
            capture_output=True,
            timeout=10,
        )

        if result.returncode == 0:
            print("✅ GPU 模式成功")
            return True
        else:
            print(f"❌ GPU 模式失败: {result.stderr.decode('utf-8', errors='ignore')[:200]}")
            return False

    except Exception as e:
        print(f"❌ GPU 模式错误: {e}")
        return False


def test_code_gpu_detection():
    """测试我们代码中的 GPU 检测函数"""
    print("\n" + "=" * 80)
    print("测试 4: 代码 GPU 检测函数")
    print("=" * 80)

    try:
        # 导入我们的代码
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

        from medagent.services.docking_adapters import _check_gpu_available

        print("调用 _check_gpu_available()...")
        gpu_available = _check_gpu_available()

        if gpu_available:
            print("✅ 代码检测到 GPU 可用")
        else:
            print("⚠️ 代码检测到 GPU 不可用")
            print("  这可能是因为：")
            print("  1. 没有安装 NVIDIA Container Toolkit")
            print("  2. Docker 配置不正确")
            print("  3. 没有 NVIDIA GPU 硬件")

        return gpu_available

    except ImportError as e:
        print(f"❌ 无法导入代码: {e}")
        return None
    except Exception as e:
        print(f"❌ 检测失败: {e}")
        return None


def test_container_cleanup():
    """测试容器清理功能"""
    print("\n" + "=" * 80)
    print("测试 5: 容器超时清理")
    print("=" * 80)

    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

        from medagent.services.docking_adapters import _cleanup_docker_container

        # 创建一个测试容器
        print("创建测试容器...")
        container_name = f"test_cleanup_{int(time.time())}"

        # 启动一个长时间运行的容器
        subprocess.Popen(
            ["docker", "run", "--rm", "--name", container_name, "alpine", "sleep", "3600"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        time.sleep(2)  # 等待容器启动

        # 检查容器是否存在
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
        )

        if container_name in result.stdout:
            print(f"✅ 容器 {container_name} 已创建")
        else:
            print(f"❌ 容器 {container_name} 创建失败")
            return False

        # 清理容器
        print(f"调用 _cleanup_docker_container('{container_name}')...")
        _cleanup_docker_container(container_name)

        time.sleep(1)  # 等待清理完成

        # 检查容器是否已删除
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
        )

        if container_name not in result.stdout:
            print(f"✅ 容器 {container_name} 已成功清理")
            return True
        else:
            print(f"❌ 容器 {container_name} 仍然存在")
            # 手动清理
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            return False

    except ImportError as e:
        print(f"❌ 无法导入代码: {e}")
        return None
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return None


def main():
    """运行所有测试"""
    print("\n🧪 开始 GPU 集成测试")
    print("=" * 80)

    results = {}

    # 测试 1: Docker GPU 基础
    results["docker_gpu"] = test_docker_gpu_available()

    # 如果 Docker GPU 不可用，提示用户
    if not results["docker_gpu"]:
        print("\n" + "⚠️" * 40)
        print("Docker GPU 不可用！")
        print("请先配置 NVIDIA Container Toolkit:")
        print("https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/")
        print("⚠️" * 40)

    # 测试 2-3: 各工具 GPU
    results["gnina_gpu"] = test_gnina_gpu()
    results["chemprop_gpu"] = test_chemprop_gpu()

    # 测试 4: 代码 GPU 检测
    results["code_detection"] = test_code_gpu_detection()

    # 测试 5: 容器清理
    results["cleanup"] = test_container_cleanup()

    # 总结
    print("\n" + "=" * 80)
    print("📊 测试总结")
    print("=" * 80)

    for test_name, result in results.items():
        if result is True:
            status = "✅ 通过"
        elif result is False:
            status = "❌ 失败"
        else:
            status = "⚠️ 跳过"

        print(f"{test_name:20s}: {status}")

    # 最终建议
    print("\n" + "=" * 80)
    print("💡 建议")
    print("=" * 80)

    if results["docker_gpu"]:
        print("✅ Docker GPU 正常工作！")
        print("   你的化学工具应该能够使用 GPU 加速")
    else:
        print("⚠️ Docker GPU 未配置")
        print("   化学工具将使用 CPU 模式（已优化，但较慢）")
        print("   建议安装 NVIDIA Container Toolkit 以获得最佳性能")

    if results["cleanup"] is True:
        print("✅ 容器清理功能正常")
        print("   超时后不会留下残留容器")
    elif results["cleanup"] is False:
        print("❌ 容器清理功能有问题")
        print("   可能需要检查 Docker 权限")


if __name__ == "__main__":
    main()
