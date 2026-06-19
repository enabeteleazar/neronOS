from __future__ import annotations

from typing import Any

from core.modules.natural_response import try_natural_response


STATUS_LABELS = {
    "queued": "en file d'attente",
    "pending": "en attente",
    "approved": "approuvé",
    "running": "en cours",
    "in_progress": "en cours",
    "tasks_completed": "en validation",
    "plan_finished": "terminé",
    "completed": "terminé",
    "failed": "en échec",
    "blocked_by_risk": "bloqué par un risque",
    "approval_required": "en attente d'approbation",
}


def _label(value: Any) -> str:
    raw = str(value or "unknown")
    return STATUS_LABELS.get(raw, raw.replace("_", " "))


def build_goal_status_fallback(status: dict[str, Any] | None) -> str:
    if not status:
        return "Je n'ai pas d'objectif actif à résumer pour le moment."

    title = (
        status.get("title")
        or status.get("goal")
        or status.get("objective")
        or status.get("goal_id")
        or "ton objectif"
    )
    state = _label(status.get("status"))
    current_step = status.get("current_step")
    progress = status.get("progress")

    parts = [f"Ton objectif « {title} » est actuellement {state}."]
    if current_step and str(current_step) != str(status.get("status")):
        parts.append(f"L'étape courante est : {current_step}.")
    if progress not in (None, ""):
        try:
            progress_value = float(progress)
            if progress_value <= 1:
                progress_value *= 100
            parts.append(f"Sa progression est d'environ {round(progress_value)}%.")
        except (TypeError, ValueError):
            pass

    checks = []
    for key, label in (
        ("compile_status", "compilation"),
        ("test_status", "tests"),
        ("validation_status", "validation"),
        ("registry_status", "Registry"),
        ("runtime_status", "Runtime"),
    ):
        value = status.get(key)
        if value and value not in {"pending", "unknown"}:
            checks.append(f"{label} : {_label(value)}")
    if checks:
        parts.append("État technique utile : " + ", ".join(checks[:5]) + ".")

    error = status.get("error")
    if error:
        parts.append(f"Point bloquant détecté : {error}.")

    return " ".join(parts)


async def build_goal_status_response_async(
    status: dict[str, Any] | None,
    *,
    question: str,
    use_llm: bool = True,
) -> dict[str, Any]:
    response = None
    if use_llm and status:
        response = await try_natural_response(
            module_name="goal",
            question=question,
            facts=status,
            instructions=(
                "2 à 5 phrases maximum. Explique l'état de l'objectif, l'étape courante "
                "et les validations utiles sans renvoyer le JSON brut."
            ),
            max_chars=900,
            max_sentences=5,
            require_first_person=False,
        )

    return {
        "response": response or build_goal_status_fallback(status),
        "llm_used": bool(response),
    }
