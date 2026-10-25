"""Protected contract observations, independent of evaluation cases/answers.

Callers must supply policy and current source references from trusted service
reads, never from job/source/model text. These observations do not decide whether
a procedure is defective, an expense is correct, or an external effect is allowed.
Unknown policy/schema versions remain unassessed until a developer binds them.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .decision_contract import OUTPUT_CONTRACT, validate_decision_shape
from .tool_schemas import schema_for

CHECKER_VERSION = "finance-trace-contract-signals-v1"
OPERATION_CONTRACT_VERSION = "finance-operation-stages-v1"
_POLICY_ID = "synthetic-organization-finance-policy-v1"
_RULE_DIGESTS = {
    "P-PREPARE": "95675905bbacec93b1613bac827e443e5977ece20141a83bdf0fd28dfb766812",
    "P-APPROVAL": "18cd8635d51331e76db8ee3ba9998141ce36119b9609d6b3924437c94ecaecab",
    "P-EXECUTE": "add441d8eab10999bbcf3bbbf9f2c68bbad2d2f7217b3789a7749baceafde628",
    "P-SETTLEMENT": "5f66aad52295ed1e190b8f9f98aaf1eb323c62a38739d4f6377b3338f1ac3bf5",
    "P-DUPLICATE": "697a6a56cecf0f030592d7aea145ebcfc9cd33746c8dfb962d07cf994b41734d",
}
_SCHEMA_DIGESTS = {
    "propose_obligation_update": "9ac2ca77b88c77dc6f2db318d29abfb4d85ffdfc6437d4fddace981169d54f27",
    "create_approval_request": "e1f283770326099375a0ecfc35c6a14669f10bf6ae31165fa3b5a3493f0265e8",
}
# Only these definite distinctions are covered. Payer/source/duplicate/policy
# gaps and other requirements are preserved without a correctness verdict.
_PREMATURE = {
    ("obligation_recording", "recipient_destination"): (
        "approval_request", "propose_obligation_update", ("P-PREPARE", "P-APPROVAL")
    ),
    ("obligation_recording", "human_approvals"): (
        "execution", "propose_obligation_update", ("P-PREPARE", "P-APPROVAL", "P-EXECUTE")
    ),
    ("approval_request", "human_approvals"): (
        "execution", "create_approval_request", ("P-APPROVAL", "P-EXECUTE")
    ),
}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _policy_binding(policy: Any) -> tuple[dict, dict[str, int]] | None:
    if not isinstance(policy, dict) or policy.get("id") != _POLICY_ID or type(policy.get("version")) is not int or policy["version"] != 1:
        return None
    if set(policy)-{"id", "version", "scope", "rules", "required_payment_approvals", "approval_policy_version"}:
        return None
    rules=policy.get("rules")
    if not isinstance(rules,list) or len(rules)!=len(_RULE_DIGESTS):
        return None
    indices={}
    for index,rule in enumerate(rules):
        if not isinstance(rule,dict) or not isinstance(rule.get("id"),str) or rule["id"] in indices:
            return None
        if type(rule.get("version")) is not int or rule["version"]!=1 or _RULE_DIGESTS.get(rule["id"])!=_digest(rule):
            return None
        indices[rule["id"]]=index
    return {"id":_POLICY_ID,"version":1,"rule_sha256":dict(_RULE_DIGESTS)},indices


def trace_contract_signals(
    output: Any,
    *,
    protected_policy: dict | None,
    current_source_refs: list[dict] | None = None,
    operation_contract_version: str = OPERATION_CONTRACT_VERSION,
) -> dict:
    """Return JSON observations; attach as trace['contract_signals'] for review.

    Evidence pointers use the reviewer's existing /trace and /immutable_policy
    envelope. Missing current source inventory leaves source references explicitly
    unverified. No free-form explanation, source instruction or tool argument can
    change the protected binding. Inputs are never mutated.
    """
    result={"checker_version":CHECKER_VERSION,"output_contract":OUTPUT_CONTRACT,"status":"blocked",
        "signals":[],"reference_issues":[],"financial_correctness":"not_assessed",
        "procedure_defect":"not_assessed","financial_effects_authorized":False}
    if operation_contract_version!=OPERATION_CONTRACT_VERSION:
        return {**result,"reason":"unknown_operation_contract_version"}
    try:
        schemas={name:schema_for(name)["parameters"] for name in _SCHEMA_DIGESTS}
        actual={name:_digest(schema) for name,schema in schemas.items()}
        if actual!=_SCHEMA_DIGESTS:
            return {**result,"reason":"protected_operation_schema_changed"}
        binding=_policy_binding(protected_policy)
    except (KeyError,TypeError,ValueError):
        return {**result,"reason":"protected_contract_unavailable"}
    if binding is None:
        return {**result,"reason":"unknown_or_changed_protected_policy"}
    policy,indices=binding
    result.update(policy_binding=policy,operation_contract={"id":"finance-operation-stages","version":1,
        "schema_sha256":actual,"operations":{
            "propose_obligation_update":{"required_fields":list(schemas["propose_obligation_update"]["required"]),
                "destination_parameter_present":False,"human_approval_parameter_present":False},
            "create_approval_request":{"required_action_fields":list(schemas["create_approval_request"]["properties"]["action"]["required"]),
                "human_approval_parameter_present":False}}})
    try:
        validate_decision_shape(output)
    except (TypeError,ValueError,AttributeError):
        return {**result,"reason":"invalid_structured_trace_output"}
    sources=None
    if current_source_refs is not None:
        if not isinstance(current_source_refs,list):
            return {**result,"reason":"invalid_trusted_source_inventory"}
        sources={}
        for source in current_source_refs:
            if not isinstance(source,dict) or not isinstance(source.get("id"),str) or not source["id"] \
                or type(source.get("version")) is not int or source["version"]<1 or source["id"] in sources:
                return {**result,"reason":"invalid_trusted_source_inventory"}
            sources[source["id"]]=source["version"]
    policy_versions={_POLICY_ID:1,**dict.fromkeys(indices,1)}
    for index,blocker in enumerate(output["blocking_requirements"]):
        pointer=f"/trace/output/blocking_requirements/{index}"
        for ref_index,ref in enumerate(blocker["supporting_refs"]):
            ref_pointer=f"{pointer}/supporting_refs/{ref_index}"
            if ref["kind"]=="policy":
                if policy_versions.get(ref["id"])!=ref["version"]:
                    result["reference_issues"].append({"code":"unknown_or_stale_policy_reference","pointer":ref_pointer,
                        "id":ref["id"],"observed_version":ref["version"],"current_version":policy_versions.get(ref["id"])})
            elif sources is None:
                result["reference_issues"].append({"code":"source_reference_not_verified","pointer":ref_pointer})
            elif sources.get(ref["id"])!=ref["version"]:
                result["reference_issues"].append({"code":"unknown_or_stale_source_reference","pointer":ref_pointer,
                    "id":ref["id"],"observed_version":ref["version"],"current_version":sources.get(ref["id"])})
        mismatch=_PREMATURE.get((blocker["stage"],blocker["requirement"]))
        if mismatch:
            later,operation,rules=mismatch
            operation_pointer=f"/trace/contract_signals/operation_contract/operations/{operation}"
            result["signals"].append({"code":"premature_requirement_for_operation_stage","pointer":pointer,
                "stage":blocker["stage"],"requirement":blocker["requirement"],"required_from_stage":later,
                "observation":"The protected operation does not require this later-stage prerequisite. Other evidence gaps remain unassessed.",
                "evidence_pointers":[pointer+"/stage",pointer+"/requirement",operation_pointer,
                    *[f"/immutable_policy/rules/{indices[rule]}" for rule in rules]],
                "trusted_refs":[{"kind":"operation_contract","id":operation,"version":1,"pointer":operation_pointer},
                    *[{"kind":"policy","id":rule,"version":1,"pointer":f"/immutable_policy/rules/{indices[rule]}"} for rule in rules]]})
    result["status"]="review_required" if result["signals"] or result["reference_issues"] else "observed"
    result["source_reference_check"]="not_supplied" if sources is None else "current_inventory_checked"
    result["coverage"]="declared premature destination/human-approval pairs and supporting reference versions only"
    return result
