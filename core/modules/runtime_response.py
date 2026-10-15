from __future__ import annotations

from typing import Any

from core.modules.natural_response import try_natural_response


def build_runtime_fallback(
    policy: dict[str, Any],
    global_context: dict[str, Any],
) -> str:
    mode = str(policy.get("runtime_mode") or policy.get("mode") or "unknown")
    context_ok = bool(global_context.get("exists", True))

    if mode in {"normal", "running", "active"} and context_ok:
        return "Tous mes services principaux sont actuellement opérationnels."

    if mode in {"survival", "degraded", "prudent"}:
        return (
            f"Mon runtime fonctionne en mode {mode}. "
            "Je limite donc mon autonomie pour préserver la stabilité du Core."
        )

    return (
        "Mon runtime répond, mais son état exact n'est pas complètement qualifié. "
        "Je conserve les détails techniques dans le payload runtime."
    )


async def build_runtime_response_async(
    policy: dict[str, Any],
    global_context: dict[str, Any],
    *,
    question: str = "Quel est ton état runtime ?",
    use_llm: bool = True,
) -> dict[str, Any]:
    facts = {
        "policy": policy,
        "global_context": global_context,
    }
    response = None

    if use_llm:
        response = await try_natural_response(
            module_name="runtime",
            question=question,
            facts=facts,
            instructions=(
                "1 à 3 phrases maximum. Résume l'état runtime et la disponibilité des services "
                "sans exposer le dictionnaire brut."
            ),
            max_chars=520,
            max_sentences=3,
            require_first_person=True,
        )

    return {
        "response": response or build_runtime_fallback(policy, global_context),
        "llm_used": bool(response),
    }
