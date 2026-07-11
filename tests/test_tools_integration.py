"""
计算化学工具集成测试

测试所有工具适配器的功能，包括：
- RDKit验证和描述符计算
- Chemprop ADMET预测
- 分子对接（GNINA/Vina/DiffDock）
- 分子生成（REINVENT4/AutoGrow4）

运行方式：
    pytest tests/test_tools_integration.py -v
    pytest tests/test_tools_integration.py::test_rdkit_enhanced -v
"""

import pytest

# 测试用SMILES
TEST_SMILES = {
    "ethanol": "CCO",
    "aspirin": "CC(=O)Oc1ccccc1C(=O)O",
    "caffeine": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
    "imatinib": "Cc1ccc(cc1Nc2nccc(n2)c3cccnc3)NC(=O)c4ccc(cc4)CN5CCN(CC5)C",
    "invalid": "INVALID_SMILES",
}


def _is_chemprop_available() -> bool:
    """检查Chemprop是否可用"""
    try:
        from medagent.services.admet_adapter import check_chemprop_available
        status = check_chemprop_available()
        return status.get("available", False)
    except Exception:
        return False


def _is_docker_available() -> bool:
    """检查Docker是否可用"""
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class TestRDKitEnhanced:
    """测试增强的RDKit功能"""

    def test_rdkit_availability(self):
        """测试RDKit是否可用"""
        from medagent.services.rdkit_enhanced import validate_and_calculate_enhanced

        result = validate_and_calculate_enhanced(TEST_SMILES["ethanol"])
        assert result.available, "RDKit应该可用"

    def test_valid_smiles_validation(self):
        """测试有效SMILES验证"""
        from medagent.services.rdkit_enhanced import validate_and_calculate_enhanced

        result = validate_and_calculate_enhanced(TEST_SMILES["aspirin"])
        assert result.valid, "阿司匹林SMILES应该有效"
        assert "rdkit_validation_passed" in result.labels
        assert result.descriptors is not None

    def test_invalid_smiles_validation(self):
        """测试无效SMILES验证"""
        from medagent.services.rdkit_enhanced import validate_and_calculate_enhanced

        result = validate_and_calculate_enhanced(TEST_SMILES["invalid"])
        assert not result.valid, "无效SMILES应该验证失败"
        assert result.reason is not None

    def test_descriptors_calculation(self):
        """测试描述符计算"""
        from medagent.services.rdkit_enhanced import validate_and_calculate_enhanced

        result = validate_and_calculate_enhanced(TEST_SMILES["caffeine"])
        assert result.valid
        assert result.descriptors is not None

        desc = result.descriptors
        # 咖啡因的基础性质
        assert 190 < desc.mw < 200, "咖啡因分子量约194"
        assert -1.2 < desc.logp < 1, "咖啡因LogP应处于低脂溶性范围"
        assert desc.hbd >= 0
        assert desc.hba >= 3

    def test_lipinski_compliance(self):
        """测试Lipinski五规则"""
        from medagent.services.rdkit_enhanced import validate_and_calculate_enhanced

        # 乙醇应该符合Lipinski规则
        result = validate_and_calculate_enhanced(TEST_SMILES["ethanol"])
        assert result.descriptors.lipinski_pass
        assert "lipinski_compliant" in result.labels

    def test_qed_calculation(self):
        """测试QED评分计算"""
        from medagent.services.rdkit_enhanced import validate_and_calculate_enhanced

        result = validate_and_calculate_enhanced(TEST_SMILES["aspirin"])
        if result.descriptors.qed is not None:
            assert 0 <= result.descriptors.qed <= 1, "QED评分应在0-1之间"

    def test_structural_alerts(self):
        """测试结构警报检测"""
        from medagent.services.rdkit_enhanced import validate_and_calculate_enhanced

        # 使用已知有PAINS的分子
        pains_smiles = "c1ccc2c(c1)c(=O)c3ccccc3c2=O"  # anthraquinone可能触发警报
        result = validate_and_calculate_enhanced(pains_smiles)

        # 检查是否检测到警报（如果RDKit版本支持）
        if result.structural_alerts:
            alert = result.structural_alerts[0]
            assert alert.catalog in ["PAINS", "BRENK", "NIH", "unknown"]
            assert alert.severity in ["high", "medium", "low"]

    def test_drug_likeness_score(self):
        """测试药物相似性评分"""
        from medagent.services.rdkit_enhanced import (
            validate_and_calculate_enhanced,
            calculate_drug_likeness_score,
        )

        result = validate_and_calculate_enhanced(TEST_SMILES["imatinib"])
        assert result.valid

        score = calculate_drug_likeness_score(result.descriptors)
        assert "overall_score" in score
        assert 0 <= score["overall_score"] <= 100
        assert score["recommendation"] in ["excellent", "good", "acceptable", "poor"]


class TestChempropAdapter:
    """测试Chemprop ADMET预测适配器"""

    def test_chemprop_availability(self):
        """测试Chemprop可用性检测"""
        from medagent.services.admet_adapter import check_chemprop_available

        status = check_chemprop_available()
        assert isinstance(status, dict)
        assert "available" in status
        # 注意：Chemprop可能不可用，这是正常的

    @pytest.mark.skipif(
        not _is_chemprop_available(),
        reason="Chemprop不可用"
    )
    def test_chemprop_prediction(self):
        """测试Chemprop ADMET预测"""
        from medagent.services.admet_adapter import (
            ChempropADMETRequest,
            run_chemprop_admet,
        )

        request = ChempropADMETRequest(
            smiles_list=[TEST_SMILES["aspirin"], TEST_SMILES["caffeine"]],
            molecule_ids=["MOL-001", "MOL-002"],
            properties=["hERG", "Ames"],
        )

        result = run_chemprop_admet(request)
        assert result.tool_name == "chemprop"

        if result.success:
            assert len(result.results) == 2
            for mol_result in result.results:
                assert mol_result.molecule_id in ["MOL-001", "MOL-002"]
                # 检查预测值
                if mol_result.hERG_probability is not None:
                    assert 0 <= mol_result.hERG_probability <= 1

    def test_chemprop_fallback(self):
        """测试Chemprop不可用时的回退行为"""
        from medagent.services.admet_adapter import (
            ChempropADMETRequest,
            run_chemprop_admet,
        )

        # 强制使用不可用的状态
        chemprop_status = {"available": False}

        request = ChempropADMETRequest(
            smiles_list=[TEST_SMILES["ethanol"]],
            molecule_ids=["MOL-001"],
        )

        result = run_chemprop_admet(request, chemprop_status)
        assert not result.success
        assert "chemprop_not_installed" in result.warnings or \
               "chemprop_unavailable" in result.adapter_mode


class TestDockingAdapters:
    """测试分子对接适配器"""

    def test_docking_request_validation(self):
        """测试对接请求验证"""
        from medagent.services.docking_adapters import (
            DockingToolRequest,
            validate_docking_request,
        )

        # 无效请求（文件不存在）
        request = DockingToolRequest(
            receptor_file="/nonexistent/receptor.pdb",
            ligand_file="/nonexistent/ligand.sdf",
            output_dir="/tmp/output",
        )

        warnings = validate_docking_request(request)
        assert len(warnings) > 0
        assert any("not_found" in w for w in warnings)

    def test_tool_selection(self):
        """测试对接工具选择逻辑"""
        from medagent.services.docking_adapters import (
            DockingToolRequest,
            select_docking_tool,
        )

        request = DockingToolRequest(
            receptor_file="test.pdb",
            ligand_file="test.sdf",
            output_dir="/tmp",
            grid_center=[0, 0, 0],
            grid_size=[20, 20, 20],
        )

        # 测试优先级：GNINA > Vina > DiffDock
        tool_status = {
            "gnina": {"available": True},
            "vina": {"available": True},
            "diffdock": {"available": True},
        }
        selected = select_docking_tool(request, tool_status)
        assert selected == "gnina", "应优先选择GNINA"

        # 只有Vina可用
        tool_status = {
            "gnina": {"available": False},
            "vina": {"available": True},
            "diffdock": {"available": False},
        }
        selected = select_docking_tool(request, tool_status)
        assert selected == "vina", "应选择Vina"

    def test_gnina_command_builder(self):
        """测试GNINA命令构建"""
        from medagent.services.docking_adapters import (
            DockingToolRequest,
            build_gnina_command,
        )

        request = DockingToolRequest(
            receptor_file="/data/receptor.pdb",
            ligand_file="/data/ligand.sdf",
            output_dir="/data/output",
            grid_center=[10.0, 20.0, 30.0],
            grid_size=[20.0, 20.0, 20.0],
            exhaustiveness=16,
            molecule_id="MOL-123",
        )

        cmd, pose_file = build_gnina_command("gnina", request)

        assert "gnina" in cmd
        assert "/data/receptor.pdb" in cmd
        assert "/data/ligand.sdf" in cmd
        assert "--exhaustiveness" in cmd
        assert "16" in cmd
        assert "MOL-123" in pose_file


class TestMoleculeGeneration:
    """测试分子生成适配器"""

    @pytest.mark.skipif(
        not _is_docker_available(),
        reason="Docker不可用"
    )
    def test_reinvent4_availability(self):
        """测试REINVENT4可用性"""
        # 检查Docker镜像是否存在
        import subprocess
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", "small-molecule-drug-design-agent-reinvent4"],
                capture_output=True,
                timeout=5,
            )
            available = result.returncode == 0
            # 镜像可能不存在，这是正常的
            assert isinstance(available, bool)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("Docker不可用")

    @pytest.mark.skipif(
        not _is_docker_available(),
        reason="Docker不可用"
    )
    def test_autogrow4_availability(self):
        """测试AutoGrow4可用性"""
        import subprocess
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", "small-molecule-drug-design-agent-autogrow4"],
                capture_output=True,
                timeout=5,
            )
            available = result.returncode == 0
            assert isinstance(available, bool)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("Docker不可用")


class TestToolsAPI:
    """测试工具API端点"""

    def test_api_imports(self):
        """测试API模块导入"""
        try:
            from medagent.api.tools_router import router
            assert router is not None
        except ImportError as e:
            pytest.fail(f"无法导入tools_router: {e}")

    def test_rdkit_validate_request_model(self):
        """测试RDKit验证请求模型"""
        from medagent.api.tools_router import RDKitValidateRequest

        request = RDKitValidateRequest(
            smiles=TEST_SMILES["aspirin"],
            calculate_descriptors=True,
            check_alerts=True,
        )

        assert request.smiles == TEST_SMILES["aspirin"]
        assert request.calculate_descriptors is True
        assert request.check_alerts is True

    def test_admet_predict_request_model(self):
        """测试ADMET预测请求模型"""
        from medagent.api.tools_router import ADMETPredictRequest

        request = ADMETPredictRequest(
            smiles_list=[TEST_SMILES["aspirin"]],
            molecule_ids=["MOL-001"],
            properties=["hERG", "Ames"],
        )

        assert len(request.smiles_list) == 1
        assert len(request.molecule_ids) == 1
        assert "hERG" in request.properties


# ============================================================================
# Pytest配置
# ============================================================================

@pytest.fixture(scope="session")
def test_output_dir(tmp_path_factory):
    """创建测试输出目录"""
    return tmp_path_factory.mktemp("tool_tests")


@pytest.fixture
def sample_smiles_file(test_output_dir):
    """创建测试SMILES文件"""
    smiles_file = test_output_dir / "test_molecules.csv"
    with open(smiles_file, "w") as f:
        f.write("smiles,name\n")
        for name, smiles in TEST_SMILES.items():
            if name != "invalid":
                f.write(f"{smiles},{name}\n")
    return smiles_file
