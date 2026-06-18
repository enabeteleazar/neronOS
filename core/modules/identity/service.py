from pathlib import Path


NERON_MD_PATH = Path("/etc/neron/memory/obsidian/identity/NERON.md")


def _read_neron_md() -> str:
    if not NERON_MD_PATH.exists():
        return ""

    return NERON_MD_PATH.read_text(encoding="utf-8", errors="ignore")


def _extract_section(text: str, title: str) -> str:
    lines = text.splitlines()
    start = None

    for i, line in enumerate(lines):
        clean = line.strip().lower()
        if clean.startswith("#") and title.lower() in clean:
            start = i + 1
            break

    if start is None:
        return ""

    collected = []
    for line in lines[start:]:
        if line.strip().startswith("#"):
            break
        if line.strip():
            collected.append(line.strip())

    return "\n".join(collected).strip()


def _fallback_identity() -> str:
    return (
        "Je suis Néron. Mon fichier d'identité NERON.md est absent ou illisible, "
        "donc je ne peux pas charger mon identité complète."
    )


def build_identity_response(kind: str = "identity") -> dict:
    text = _read_neron_md()

    if not text:
        response = _fallback_identity()
        source = "identity_module:fallback"
    else:
        identity = _extract_section(text, "Identité")
        mission = _extract_section(text, "Mission")

        parts = []

        if identity:
            parts.append(identity)

        if mission:
            parts.append(mission)

        if not parts:
            response = _fallback_identity()
            source = "identity_module:fallback"
        else:
            response = "\n\n".join(parts)
            source = "NERON.md"

    return {
        "response": response,
        "intent": "identity_query",
        "agent": "identity_module",
        "confidence": "high",
        "source": source,
        "identity_kind": kind,
    }
