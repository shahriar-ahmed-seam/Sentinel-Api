"""Orchestrator: turn a validated request into the response dict.

Pure and deterministic. Every enum value is sourced from config constants, and a
final clamp guarantees the output can never contain an out-of-spec enum (a bad
reasoning branch degrades gracefully instead of emitting an invalid schema).
"""

from __future__ import annotations

from typing import Optional

from . import config as C
from . import llm, settings
from .classify import classify
from .extract import extract
from .matching import match
from .responses import render
from .routing import (
    confidence_of,
    department_of,
    needs_human_review,
    severity_of,
)
from .safety import (
    is_reply_safe,
    scrub_customer_reply,
    scrub_recommended_action,
)
from .schemas import AnalyzeRequest, Txn, parse_transactions


def _build_reason_codes(
    case_type: str,
    verdict: str,
    relevant_id: Optional[str],
    meta: dict,
    injection: bool,
    human_review: bool,
    high_value: bool,
) -> list[str]:
    codes: list[str] = [case_type]

    if case_type == C.PHISHING:
        codes += ["credential_protection", "critical_escalation"]

    if verdict == C.CONSISTENT and relevant_id is not None:
        codes.append("transaction_match")
    elif verdict == C.INCONSISTENT:
        codes.append("evidence_inconsistent")
        if meta.get("established_recipient"):
            codes.append("established_recipient_pattern")
        if meta.get("status_contradiction"):
            codes.append("status_contradiction")
        if meta.get("single_charge_only"):
            codes.append("single_charge_only")
    elif verdict == C.INSUFFICIENT:
        if meta.get("ambiguous"):
            codes += ["ambiguous_match", "needs_clarification"]
        elif case_type == C.OTHER:
            codes += ["vague_complaint", "needs_clarification"]
        elif case_type != C.PHISHING:
            codes += ["insufficient_evidence", "needs_clarification"]

    if meta.get("duplicate_of"):
        codes.append("duplicate_detected")
    if high_value:
        codes.append("high_value")
    if human_review:
        codes.append("human_review")
    if injection:
        codes.append("prompt_injection_ignored")

    # De-duplicate while preserving order.
    seen: set[str] = set()
    return [c for c in codes if not (c in seen or seen.add(c))]


def _clamp(value: str, allowed: tuple[str, ...], default: str) -> str:
    return value if value in allowed else default


def _apply_llm(
    texts: dict,
    decision: dict,
    reply_lang: str,
    complaint: str,
    history: list[Txn],
) -> tuple[str, str, str, bool]:
    """Assist-only enrichment: replace each rule template with the LLM draft ONLY
    if the draft passes the safety checks; otherwise keep the rule template.
    Never touches the scored decision fields. Returns (summary, action, reply,
    llm_used)."""
    summary = texts["agent_summary"]
    action = texts["recommended_next_action"]
    reply = texts["customer_reply"]

    if not settings.llm_enabled():
        return summary, action, reply, False

    compact = [
        {
            "transaction_id": t.transaction_id,
            "type": t.type,
            "amount": t.amount,
            "counterparty": t.counterparty,
            "status": t.status,
        }
        for t in history[:8]
    ]
    prompt_decision = dict(decision)
    prompt_decision["baseline_reply"] = reply

    draft = llm.draft_texts(prompt_decision, complaint, reply_lang, compact)
    if not draft:
        return summary, action, reply, False

    used = False
    cand_reply = draft.get("customer_reply")
    if cand_reply and is_reply_safe(cand_reply):
        reply, used = cand_reply, True
    cand_summary = draft.get("agent_summary")
    if cand_summary and is_reply_safe(cand_summary):
        summary, used = cand_summary, True
    cand_action = draft.get("recommended_next_action")
    if cand_action and is_reply_safe(cand_action):
        action, used = cand_action, True

    return summary, action, reply, used


async def _apply_llm_async(
    texts: dict,
    decision: dict,
    reply_lang: str,
    complaint: str,
    history: list[Txn],
) -> tuple[str, str, str, bool]:
    """Async counterpart of `_apply_llm`, used by the live server."""
    summary = texts["agent_summary"]
    action = texts["recommended_next_action"]
    reply = texts["customer_reply"]

    if not settings.llm_enabled():
        return summary, action, reply, False

    compact = [
        {
            "transaction_id": t.transaction_id,
            "type": t.type,
            "amount": t.amount,
            "counterparty": t.counterparty,
            "status": t.status,
        }
        for t in history[:8]
    ]
    prompt_decision = dict(decision)
    prompt_decision["baseline_reply"] = reply

    draft = await llm.draft_texts_async(prompt_decision, complaint, reply_lang, compact)
    if not draft:
        return summary, action, reply, False

    used = False
    cand_reply = draft.get("customer_reply")
    if cand_reply and is_reply_safe(cand_reply):
        reply, used = cand_reply, True
    cand_summary = draft.get("agent_summary")
    if cand_summary and is_reply_safe(cand_summary):
        summary, used = cand_summary, True
    cand_action = draft.get("recommended_next_action")
    if cand_action and is_reply_safe(cand_action):
        action, used = cand_action, True

    return summary, action, reply, used


def _decide(req: AnalyzeRequest) -> dict:
    """Run the deterministic rule pipeline. Returns a context dict with the
    complete (already-safe) rule answer and everything the optional LLM and the
    finalizer need."""
    history = parse_transactions(req.transaction_history)
    feats = extract(req.complaint, req.language)

    case_type = classify(feats, req.user_type, history)
    relevant_id, verdict, meta = match(case_type, feats, history)
    amount = meta.get("amount")

    severity = severity_of(case_type, verdict, relevant_id, amount)
    department = department_of(case_type, req.user_type, severity, verdict)
    human_review = needs_human_review(
        case_type, verdict, relevant_id, severity, amount
    )

    texts = render(case_type, verdict, relevant_id, meta, feats, req.user_type)

    decision = {
        "case_type": case_type,
        "evidence_verdict": verdict,
        "severity": severity,
        "department": department,
        "relevant_transaction_id": relevant_id,
        "human_review_required": human_review,
        "amount": meta.get("amount"),
        "counterparty": meta.get("counterparty"),
        "status": getattr(meta.get("txn"), "status", None),
    }

    return {
        "history": history,
        "feats": feats,
        "case_type": case_type,
        "verdict": verdict,
        "relevant_id": relevant_id,
        "meta": meta,
        "amount": amount,
        "severity": severity,
        "department": department,
        "human_review": human_review,
        "texts": texts,
        "decision": decision,
    }


def _finalize(
    req: AnalyzeRequest,
    ctx: dict,
    agent_summary: str,
    next_action_text: str,
    reply_text: str,
    llm_used: bool,
) -> dict:
    """Apply the binding safety net, build reason codes, and assemble the
    schema-clamped response dict. Shared by the sync and async entry points."""
    case_type = ctx["case_type"]
    verdict = ctx["verdict"]
    relevant_id = ctx["relevant_id"]
    meta = ctx["meta"]
    amount = ctx["amount"]
    feats = ctx["feats"]

    # Final binding safety net (no-op when the chosen text is already safe).
    customer_reply = scrub_customer_reply(reply_text, feats.reply_lang)
    next_action = scrub_recommended_action(next_action_text)

    high_value = (
        amount is not None
        and amount >= C.HIGH_VALUE_BDT
        and case_type in C.MONEY_MOVEMENT_CASES
    )
    reason_codes = _build_reason_codes(
        case_type, verdict, relevant_id, meta, feats.injection, ctx["human_review"], high_value
    )
    if settings.llm_enabled():
        reason_codes.append("llm_text_used" if llm_used else "llm_fallback_rules")

    # Final enum clamp — guarantees a schema-valid response no matter what.
    return {
        "ticket_id": req.ticket_id,
        "relevant_transaction_id": relevant_id,
        "evidence_verdict": _clamp(verdict, C.EVIDENCE_VERDICTS, C.INSUFFICIENT),
        "case_type": _clamp(case_type, C.CASE_TYPES, C.OTHER),
        "severity": _clamp(ctx["severity"], C.SEVERITIES, C.MEDIUM),
        "department": _clamp(ctx["department"], C.DEPARTMENTS, C.CUSTOMER_SUPPORT),
        "agent_summary": agent_summary,
        "recommended_next_action": next_action,
        "customer_reply": customer_reply,
        "human_review_required": bool(ctx["human_review"]),
        "confidence": round(float(confidence_of(case_type, verdict, meta)), 2),
        "reason_codes": reason_codes,
    }


def analyze(req: AnalyzeRequest) -> dict:
    """Synchronous entry point (used by tests and any non-async caller)."""
    ctx = _decide(req)
    agent_summary, next_action_text, reply_text, llm_used = _apply_llm(
        ctx["texts"], ctx["decision"], ctx["feats"].reply_lang, req.complaint, ctx["history"]
    )
    return _finalize(req, ctx, agent_summary, next_action_text, reply_text, llm_used)


async def analyze_async(req: AnalyzeRequest) -> dict:
    """Async entry point used by the live server: the rule decision runs inline
    and only the optional LLM enrichment awaits I/O over a pooled,
    concurrency-bounded client."""
    ctx = _decide(req)
    agent_summary, next_action_text, reply_text, llm_used = await _apply_llm_async(
        ctx["texts"], ctx["decision"], ctx["feats"].reply_lang, req.complaint, ctx["history"]
    )
    return _finalize(req, ctx, agent_summary, next_action_text, reply_text, llm_used)
