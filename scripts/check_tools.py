#!/usr/bin/env python
"""
计算化学工具检测脚本

检查所有必需的化学计算工具是否可用：
- RDKit：分子验证和描述符计算
- Chemprop：ADMET预测
- GNINA/Vina：分子对接
- DiffDock：基于扩散模型的对接
- REINVENT4：强化学习分子生成
- AutoGrow4：遗传算法分子生成
- AiZynthFinder：逆合成路线分析

用法：
    python scripts/check_tools.py
    python scripts/check_tools.py --verbose
    python scripts/check_tools.py --test
"""

import argparse
import importlib
import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")

# 添加src目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def check_rdkit() -> dict[str, Any]:
    """检查RDKit可用性"""
    result = {
        "name": "RDKit",
        "available": False,
        "version": None,
        "features": [],
        "missing": [],
    }

    try:
        rdkit = importlib.import_module("rdkit")
        importlib.import_module("rdkit.Chem")
        result["available"] = True
        result["version"] = getattr(rdkit, "__version__", "unknown")
        result["features"].append("Chem")

        # 检查额外模块
        try:
            importlib.import_module("rdkit.Chem.Crippen")
            importlib.import_module("rdkit.Chem.Descriptors")
            importlib.import_module("rdkit.Chem.Lipinski")
            result["features"].append("Descriptors")
        except ImportError:
            result["missing"].append("Descriptors")

        try:
            importlib.import_module("rdkit.Chem.FilterCatalog")
            result["features"].append("FilterCatalog (PAINS/Brenk)")
        except ImportError:
            result["missing"].append("FilterCatalog")

        try:
            importlib.import_module("rdkit.Chem.Scaffolds.MurckoScaffold")
            result["features"].append("MurckoScaffold")
        except ImportError:
            result["missing"].append("MurckoScaffold")

        try:
            importlib.import_module("rdkit.Chem.rdMolDescriptors")
            result["features"].append("rdMolDescriptors")
        except ImportError:
            result["missing"].append("rdMolDescriptors")

        try:
            importlib.import_module("rdkit.Chem.AllChem")
            result["features"].append("AllChem (3D)")
        except ImportError:
            result["missing"].append("AllChem")

    except ImportError as e:
        result["error"] = str(e)

    return result


def _check_admet_ai_models() -> dict[str, Any] | None:
    """Detect ADMET-AI's bundled Chemprop ADMET model ensembles."""
    spec = importlib.util.find_spec("admet_ai")
    if spec is None or spec.origin is None:
        return None

    package_dir = Path(spec.origin).parent
    models_dir = package_dir / "resources" / "models"
    required_dirs = [
        models_dir / "admet_classification",
        models_dir / "admet_regression",
    ]
    if not all(path.exists() for path in required_dirs):
        return None

    model_files = list(models_dir.rglob("*.pt"))
    if not model_files:
        return None

    try:
        version = importlib.metadata.version("admet-ai")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"

    return {
        "version": version,
        "models_dir": str(models_dir),
        "model_count": len(model_files),
    }


def check_chemprop() -> dict[str, Any]:
    """检查Chemprop可用性"""
    result = {
        "name": "Chemprop",
        "available": False,
        "mode": None,
        "version": None,
        "path": None,
        "models_dir": None,
        "model_count": None,
    }

    # 检查Python包
    admet_ai_status = _check_admet_ai_models()
    if admet_ai_status:
        result["available"] = True
        result["mode"] = "admet_ai"
        result["version"] = admet_ai_status["version"]
        result["models_dir"] = admet_ai_status["models_dir"]
        result["model_count"] = admet_ai_status["model_count"]
        return result

    try:
        import chemprop
        result["available"] = True
        result["mode"] = "python_package"
        result["version"] = getattr(chemprop, "__version__", "unknown")
        return result
    except ImportError:
        pass

    # 检查CLI
    cli_status = _check_chemprop_cli()
    if cli_status:
        result["available"] = True
        result["mode"] = "cli"
        result["version"] = cli_status["version"]
        result["path"] = cli_status["path"]
        if cli_status.get("warning"):
            result["warning"] = cli_status["warning"]
        return result

    # 检查Docker
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", "chemprop:latest"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0:
            result["available"] = True
            result["mode"] = "docker"
            result["docker_image"] = "chemprop:latest"
            return result
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return result


def _check_chemprop_cli() -> dict[str, Any] | None:
    """Detect Chemprop CLI versions with and without --version support."""
    path = shutil.which("chemprop")
    if path is None:
        return None

    try:
        proc = subprocess.run(
            ["chemprop", "--version"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {
            "version": "unknown",
            "path": path,
            "warning": "chemprop_cli_version_unavailable",
        }

    if proc.returncode == 0:
        return {"version": proc.stdout.strip() or "unknown", "path": path}

    return {
        "version": "unknown",
        "path": path,
        "warning": "chemprop_cli_version_unavailable",
    }


def check_gnina() -> dict[str, Any]:
    """检查GNINA可用性"""
    result = {
        "name": "GNINA",
        "available": False,
        "version": None,
        "path": None,
    }

    # 检查CLI
    try:
        proc = subprocess.run(
            ["gnina", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            result["available"] = True
            result["version"] = proc.stdout.strip()
            result["path"] = "gnina"
            return result
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 检查Docker
    gnina_images = [
        os.environ.get("GNINA_IMAGE", "gnina/gnina:latest"),
        "gnina/gnina:latest",
        "gnina/gnina:1.0.3",
        "gnina:latest",
    ]
    for image in dict.fromkeys(gnina_images):
        try:
            proc = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0:
                result["available"] = True
                result["mode"] = "docker"
                result["docker_image"] = image
                return result
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return result


def check_vina() -> dict[str, Any]:
    """检查AutoDock Vina可用性"""
    result = {
        "name": "AutoDock Vina",
        "available": False,
        "version": None,
        "path": None,
    }

    # 检查CLI
    for cmd in ["vina", "autodock_vina", "vina_1_1_2"]:
        try:
            proc = subprocess.run(
                [cmd, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0 or "AutoDock Vina" in proc.stdout:
                result["available"] = True
                result["version"] = proc.stdout.strip()
                result["path"] = cmd
                return result
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    # 检查Docker
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", "vina:latest"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            result["available"] = True
            result["mode"] = "docker"
            result["docker_image"] = "vina:latest"
            return result
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return result


def check_diffdock() -> dict[str, Any]:
    """检查DiffDock可用性"""
    result = {
        "name": "DiffDock",
        "available": False,
        "mode": None,
        "version": None,
    }

    # 检查Python包
    try:
        import diffdock
        result["available"] = True
        result["mode"] = "python_package"
        result["version"] = getattr(diffdock, "__version__", "unknown")
        return result
    except ImportError:
        pass

    # 检查Docker
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", "diffdock:latest"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            result["available"] = True
            result["mode"] = "docker"
            result["docker_image"] = "diffdock:latest"
            return result
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return result


def check_reinvent4() -> dict[str, Any]:
    """检查REINVENT4可用性"""
    from medagent.services.reinvent4_adapter import reinvent4_tool_status

    status = reinvent4_tool_status()
    return {
        "name": "REINVENT4",
        "available": status["available"],
        "mode": status.get("mode"),
        "version": status.get("version"),
        "docker_image": status.get("docker_image"),
    }


def check_autogrow4() -> dict[str, Any]:
    """检查AutoGrow4可用性"""
    from medagent.services.autogrow4_adapter import autogrow4_tool_status

    status = autogrow4_tool_status()
    return {
        "name": "AutoGrow4",
        "available": status["available"],
        "mode": status.get("mode"),
        "version": status.get("version"),
        "docker_image": status.get("docker_image"),
    }


def check_aizynthfinder() -> dict[str, Any]:
    """检查AiZynthFinder可用性"""
    from medagent.services.aizynthfinder_adapter import aizynthfinder_tool_status

    status = aizynthfinder_tool_status()
    return {
        "name": "AiZynthFinder",
        "available": status["available"],
        "mode": status.get("mode"),
        "version": status.get("version"),
        "path": status.get("path"),
        "docker_image": status.get("docker_image"),
        "model_configured": status.get("model_configured", False),
    }


def print_tool_status(result: dict[str, Any], verbose: bool = False) -> None:
    """打印工具状态"""
    name = result["name"]
    available = result["available"]

    status = "✅" if available else "❌"
    print(f"\n{status} {name}")

    if available:
        if result.get("version"):
            print(f"   版本: {result['version']}")
        if result.get("mode"):
            print(f"   模式: {result['mode']}")
        if result.get("path"):
            print(f"   路径: {result['path']}")
        if result.get("docker_image"):
            print(f"   Docker镜像: {result['docker_image']}")
        if result.get("models_dir"):
            print(f"   ADMET-AI models: {result['models_dir']}")
        if result.get("model_count") is not None:
            print(f"   Model files: {result['model_count']}")
        if "model_configured" in result:
            print(f"   Model configured: {result['model_configured']}")
        if result.get("features") and verbose:
            print(f"   功能: {', '.join(result['features'])}")
        if result.get("missing") and verbose:
            print(f"   缺失: {', '.join(result['missing'])}")
    else:
        print("   状态: 未安装或不可用")
        if result.get("error") and verbose:
            print(f"   错误: {result['error']}")


def test_rdkit_basic() -> bool:
    """测试RDKit基本功能"""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors

        # 测试SMILES解析
        mol = Chem.MolFromSmiles("CCO")
        if mol is None:
            print("   ❌ SMILES解析失败")
            return False

        # 测试描述符计算
        mw = Descriptors.MolWt(mol)
        if not (40 < mw < 50):
            print(f"   ❌ 分子量计算异常: {mw}")
            return False

        print("   ✅ 基本功能正常")
        return True
    except Exception as e:
        print(f"   ❌ 测试失败: {e}")
        return False


def test_chemprop_basic() -> bool:
    """测试Chemprop基本功能"""
    try:
        from medagent.services.admet_adapter import check_chemprop_available

        status = check_chemprop_available()
        if status["available"]:
            print(f"   ✅ Chemprop可用 (模式: {status.get('mode')})")
            return True
        else:
            print("   ⚠️  Chemprop不可用，将使用RDKit代理")
            return False
    except Exception as e:
        print(f"   ❌ 测试失败: {e}")
        return False


def test_aizynthfinder_basic() -> bool:
    """测试AiZynthFinder适配器和模型配置状态"""
    try:
        from medagent.services.aizynthfinder_adapter import aizynthfinder_tool_status

        status = aizynthfinder_tool_status()
        if not status["available"]:
            print("   ⚠️  AiZynthFinder不可用，将使用RDKit规则回退")
            return False
        if not status.get("model_configured"):
            print("   ⚠️  AiZynthFinder已安装，但未配置可读的AiZynthFinder配置文件")
            print("      设置 AIZYNTHFINDER_CONFIG 或 MEDAGENT_AIZYNTHFINDER_CONFIG")
            return False

        print(f"   ✅ AiZynthFinder可用 (模式: {status.get('mode')})")
        return True
    except Exception as e:
        print(f"   ❌ 测试失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="检查计算化学工具可用性")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细信息")
    parser.add_argument("--test", "-t", action="store_true", help="运行基本功能测试")
    args = parser.parse_args()

    print("=" * 60)
    print("小分子药物设计Agent - 计算工具检测")
    print("=" * 60)

    # 检查所有工具
    tools = [
        check_rdkit(),
        check_chemprop(),
        check_gnina(),
        check_vina(),
        check_diffdock(),
        check_reinvent4(),
        check_autogrow4(),
        check_aizynthfinder(),
    ]

    for tool in tools:
        print_tool_status(tool, args.verbose)

    # 统计
    available_count = sum(1 for t in tools if t["available"])
    total_count = len(tools)

    print("\n" + "=" * 60)
    print(f"可用工具: {available_count}/{total_count}")
    print("=" * 60)

    # 运行测试
    if args.test:
        print("\n🧪 运行基本功能测试...\n")

        print("测试 RDKit:")
        test_rdkit_basic()

        print("\n测试 Chemprop:")
        test_chemprop_basic()

        print("\n测试 AiZynthFinder:")
        test_aizynthfinder_basic()

    # 给出建议
    print("\n📋 建议:")

    rdkit_available = any(t["name"] == "RDKit" and t["available"] for t in tools)
    if not rdkit_available:
        print("   ⚠️  RDKit是必需的！请安装: pip install rdkit")

    chemprop_available = any(t["name"] == "Chemprop" and t["available"] for t in tools)
    if not chemprop_available:
        print("   💡 安装Chemprop以获得真实ADMET预测: pip install chemprop")
        print("      或使用Docker: docker compose build chemprop")

    docking_available = any(
             t["name"] in ["GNINA", "AutoDock Vina", "DiffDock"] and t["available"]
        for t in tools
    )
    if not docking_available:
        print("   💡 安装对接工具以进行分子对接:")
        print("      GNINA: https://github.com/gnina/gnina")
        print("      或使用Docker: docker compose pull gnina")

    generation_available = any(
        t["name"] in ["REINVENT4", "AutoGrow4"] and t["available"]
        for t in tools
    )
    if not generation_available:
        print("   💡 安装分子生成工具:")
        print("      REINVENT4: pip install reinvent4")
        print("      或使用Docker: docker compose build reinvent4")

    retrosynthesis_available = any(
        t["name"] == "AiZynthFinder" and t["available"]
        for t in tools
    )
    if not retrosynthesis_available:
        print("   💡 安装AiZynthFinder以获得真实逆合成路线: pip install aizynthfinder")

    print("\n✨ 即使工具不完整，系统也会使用RDKit代理回退机制保证可用性")

    return 0 if available_count >= 1 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
