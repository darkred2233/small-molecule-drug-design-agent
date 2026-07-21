"""Validation and user-override handling for central round strategies."""

from __future__ import annotations

import copy
from typing import Any


class StrategyValidationError(Exception):
    """Raised when a strategy cannot produce an executable generation plan."""


class StrategyValidator:
    MAX_CREM_MOLECULES = 500
    MAX_REINVENT4_MOLECULES = 1000
    MAX_AUTOGROW4_MOLECULES = 300
    MAX_AUTOGROW4_GENERATIONS = 50
    MW_MIN = 100
    MW_MAX = 1000
    LOGP_MIN = -5
    LOGP_MAX = 10
    TPSA_MIN = 0
    TPSA_MAX = 300

    def __init__(self, settings: Any | None = None):
        self.settings = settings

    def validate_and_fix(
        self,
        strategy_draft: dict[str, Any],
        tool_availability: dict[str, Any] | None = None,
        user_overrides: dict[str, Any] | None = None,
        data_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        validated = copy.deepcopy(strategy_draft) if isinstance(strategy_draft, dict) else {}
        warnings: list[str] = list(validated.get("warnings") or [])
        if isinstance(user_overrides, dict) and user_overrides:
            validated = self._apply_user_overrides(validated, user_overrides, warnings)

        data_context = data_context or validated.get("context_snapshot") or {}
        if not isinstance(data_context, dict):
            data_context = {}
        if not isinstance(tool_availability, dict):
            tool_availability = {}
        validated["campaign_config"] = self._validate_campaign_config(
            validated.get("campaign_config")
            if isinstance(validated.get("campaign_config"), dict)
            else {},
            tool_availability or {},
            data_context,
            warnings,
        )
        validated["property_constraints"] = self._validate_property_constraints(
            validated.get("property_constraints")
            if isinstance(validated.get("property_constraints"), dict)
            else {},
            warnings,
        )
        validated["assessment_config"] = self._validate_assessment_config(
            validated.get("assessment_config")
            if isinstance(validated.get("assessment_config"), dict)
            else {},
            warnings,
        )
        validated["seed_policy"] = self._validate_seed_policy(
            validated.get("seed_policy")
            if isinstance(validated.get("seed_policy"), dict)
            else {},
            data_context,
            warnings,
        )

        enabled_methods = [
            method
            for method, config in validated["campaign_config"].items()
            if isinstance(config, dict) and config.get("enabled") and config.get("num_molecules", config.get("sample_count", 0)) > 0
        ]
        if not enabled_methods:
            raise StrategyValidationError("至少需要启用一种生成方法并分配大于 0 的生成数量")

        validated["warnings"] = warnings
        validated.setdefault("requires_user_confirmation", True)
        return validated

    def _validate_campaign_config(
        self,
        campaign_config: dict[str, Any],
        tool_availability: dict[str, Any],
        data_context: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for method in ("crem", "reinvent4", "autogrow4"):
            value = campaign_config.get(method) or {}
            normalized[method] = dict(value) if isinstance(value, dict) else {}

        crem = normalized["crem"]
        crem["num_molecules"] = self._bounded_count(
            crem.get("num_molecules", 100), self.MAX_CREM_MOLECULES, 50, warnings, "CReM"
        )
        crem["edit_depth"] = self._bounded_int(crem.get("edit_depth", 2), 1, 5, 2)
        self._disable_if_unavailable(crem, "crem", tool_availability, warnings)
        has_seed_source = bool(
            self._data_count(data_context, "seed_ligand_count")
            or data_context.get("previous_molecule_count")
            or data_context.get("previous_ranked_molecule_ids")
        )
        if crem.get("enabled") and not has_seed_source:
            crem["enabled"] = False
            warnings.append("CReM 需要至少一个 seed ligand，当前轮次已禁用")

        reinvent4 = normalized["reinvent4"]
        if "sample_count" not in reinvent4 and "num_molecules" in reinvent4:
            reinvent4["sample_count"] = reinvent4.pop("num_molecules")
        reinvent4["sample_count"] = self._bounded_count(
            reinvent4.get("sample_count", 100), self.MAX_REINVENT4_MOLECULES, 10, warnings, "REINVENT4"
        )
        mode_aliases = {
            "sampling": "rl_only",
            "light_transfer": "light_tl_then_rl",
            "full_transfer": "tl_then_rl",
        }
        mode = mode_aliases.get(reinvent4.get("mode"), reinvent4.get("mode", "rl_only"))
        if mode not in {"rl_only", "light_tl_then_rl", "tl_then_rl"}:
            mode = "rl_only"
            warnings.append("REINVENT4 模式无效，已调整为 rl_only")
        reinvent4["mode"] = mode
        reinvent4["rl_steps"] = self._bounded_int(reinvent4.get("rl_steps", 30), 5, 200, 30)
        reinvent4["batch_size"] = self._bounded_int(reinvent4.get("batch_size", 128), 16, 1024, 128)
        self._disable_if_unavailable(reinvent4, "reinvent4", tool_availability, warnings)

        autogrow4 = normalized["autogrow4"]
        autogrow4["num_molecules"] = self._bounded_count(
            autogrow4.get("num_molecules", 100), self.MAX_AUTOGROW4_MOLECULES, 50, warnings, "AutoGrow4"
        )
        autogrow4["generations"] = self._bounded_int(
            autogrow4.get("generations", 5), 1, self.MAX_AUTOGROW4_GENERATIONS, 5
        )
        autogrow4.setdefault("search_intensity", "normal")
        autogrow4.setdefault("source_pool_policy", "auto")
        if autogrow4["search_intensity"] not in {"quick", "normal", "heavy"}:
            autogrow4["search_intensity"] = "normal"
            warnings.append("AutoGrow4 搜索强度无效，已调整为 normal")
        if autogrow4["source_pool_policy"] not in {
            "auto", "target_ligands", "previous_top", "user_uploaded"
        }:
            autogrow4["source_pool_policy"] = "auto"
            warnings.append("AutoGrow4 source pool 策略无效，已调整为 auto")
        self._disable_if_unavailable(autogrow4, "autogrow4", tool_availability, warnings)
        summary = data_context.get("data_summary") or {}
        has_receptor = bool(
            summary.get("prepared_binding_site_count") or summary.get("binding_site_count")
        )
        has_source_pool = bool(
            summary.get("target_ligand_count")
            or summary.get("seed_ligand_count")
            or summary.get("uploaded_file_count")
        )
        if autogrow4.get("enabled") and not has_receptor:
            autogrow4["enabled"] = False
            warnings.append("AutoGrow4 需要 receptor/binding site 资源，当前轮次已禁用")
        elif autogrow4.get("enabled") and not has_source_pool:
            autogrow4["enabled"] = False
            warnings.append("AutoGrow4 需要 source compound pool，当前轮次已禁用")

        return normalized

    def _validate_property_constraints(
        self,
        property_constraints: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        ranges = {
            "mw_range": (self.MW_MIN, self.MW_MAX),
            "logp_range": (self.LOGP_MIN, self.LOGP_MAX),
            "tpsa_range": (self.TPSA_MIN, self.TPSA_MAX),
            "hbd_range": (0, 20),
            "hba_range": (0, 30),
        }
        validated: dict[str, Any] = {}
        for field, (minimum, maximum) in ranges.items():
            value = property_constraints.get(field)
            if not isinstance(value, list) or len(value) != 2:
                continue
            try:
                lower = max(minimum, min(float(value[0]), maximum))
                upper = max(minimum, min(float(value[1]), maximum))
            except (TypeError, ValueError):
                warnings.append(f"{field} 不是有效范围，已忽略")
                continue
            if lower > upper:
                lower, upper = upper, lower
            if field in {"hbd_range", "hba_range"}:
                normalized = [int(lower), int(upper)]
            else:
                normalized = [lower, upper]
            validated[field] = normalized
            if normalized != value:
                warnings.append(f"{field} 已裁剪到允许范围")
        return validated

    def _validate_assessment_config(
        self,
        assessment_config: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        validated = dict(assessment_config)
        mode = validated.get("mode", "external_top_n")
        if mode not in {"all", "external_top_n", "fast"}:
            mode = "external_top_n"
            warnings.append("评估模式无效，已调整为 external_top_n")
        validated["mode"] = mode
        if mode == "external_top_n":
            validated["top_n"] = self._bounded_int(validated.get("top_n", 50), 1, 200, 50)
        for field in ("skip_docking", "skip_admet", "skip_synthesis"):
            validated[field] = self._as_bool(validated.get(field, False))
        return validated

    def _validate_seed_policy(
        self,
        seed_policy: dict[str, Any],
        data_context: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        validated = dict(seed_policy)
        source = validated.get("source", "all_seeds")
        if source not in {"all_seeds", "top_from_previous", "mixed"}:
            source = "all_seeds"
            warnings.append("seed_policy.source 无效，已调整为 all_seeds")
        validated["source"] = source
        if source in {"top_from_previous", "mixed"}:
            validated["top_n"] = self._bounded_int(validated.get("top_n", 10), 1, 50, 10)
        previous_ids = set(data_context.get("previous_ranked_molecule_ids") or [])
        requested_ids = [str(item) for item in validated.get("molecule_ids") or []]
        if previous_ids:
            accepted_ids = [item for item in requested_ids if item in previous_ids]
            if len(accepted_ids) != len(requested_ids):
                warnings.append("seed_policy 中存在不属于上一轮排名的分子，已移除")
            validated["molecule_ids"] = accepted_ids
        else:
            validated["molecule_ids"] = []
        return validated

    def _apply_user_overrides(
        self,
        strategy: dict[str, Any],
        user_overrides: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        if "disable_methods" in user_overrides:
            for method in user_overrides["disable_methods"]:
                config = strategy.setdefault("campaign_config", {}).setdefault(method, {})
                config["enabled"] = False
                warnings.append(f"根据用户要求已禁用 {method}")
        for field in ("objective", "seed_policy", "property_constraints", "assessment_config"):
            if field in user_overrides:
                strategy[field] = copy.deepcopy(user_overrides[field])
                warnings.append(f"根据用户要求已覆盖 {field}")
        user_campaign = user_overrides.get("campaign_config")
        if isinstance(user_campaign, dict):
            campaign = strategy.setdefault("campaign_config", {})
            for method, config in user_campaign.items():
                if isinstance(config, dict):
                    campaign.setdefault(method, {}).update(copy.deepcopy(config))
                    warnings.append(f"根据用户要求已覆盖 {method} 配置")
        return strategy

    @staticmethod
    def _disable_if_unavailable(
        config: dict[str, Any],
        method: str,
        tool_availability: dict[str, Any],
        warnings: list[str],
    ) -> None:
        if config.get("enabled") and not StrategyValidator._is_available(tool_availability.get(method, False)):
            config["enabled"] = False
            warnings.append(f"{method} 工具不可用，已自动禁用")

    @staticmethod
    def _is_available(value: Any) -> bool:
        if isinstance(value, dict):
            return bool(value.get("available"))
        return bool(value)

    @staticmethod
    def _data_count(context: dict[str, Any], key: str) -> int:
        return int((context.get("data_summary") or {}).get(key, 0) or 0)

    @staticmethod
    def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(parsed, maximum))

    def _bounded_count(
        self,
        value: Any,
        maximum: int,
        minimum: int,
        warnings: list[str],
        method: str,
    ) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = minimum
            warnings.append(f"{method} 生成数量无效，已调整为 {minimum}")
        if parsed > maximum:
            warnings.append(f"{method} 生成数量超过上限，已调整为 {maximum}")
        if 0 < parsed < minimum:
            warnings.append(f"{method} 生成数量过少，已调整为 {minimum}")
        return max(0, min(parsed, maximum)) if parsed == 0 else max(minimum, min(parsed, maximum))

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
