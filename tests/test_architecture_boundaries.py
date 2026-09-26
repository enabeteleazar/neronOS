"""Cliquet architectural : le couplage inter-plateformes ne doit que decroitre.

Ce module ne teste pas un comportement mais une PROPRIETE DE STRUCTURE. Il a ete
introduit en Phase 2A pour rendre mesurable — et irreversible — le decouplage de
Core prevu en Phase 2B.

Trois invariants :

1. `server/common` reste un puits : il n'importe aucune plateforme. C'est ce qui
   en fait la destination sure des primitives noyau extraites de Core.
2. L'ensemble des paquets pris dans le cycle ne s'agrandit pas.
3. Aucune arete inter-plateformes ne gagne de sites d'import.

Le point 3 est un cliquet : faire baisser un compteur est encourage (il suffit de
mettre a jour BASELINE a la baisse), le faire monter echoue. Quand une arete
tombe a zero, retirez-la de BASELINE.
"""

from __future__ import annotations

import ast
import collections
import pathlib

import pytest

SERVER = pathlib.Path(__file__).resolve().parents[1] / "server"

# Paquets de premier niveau sous server/ traites comme des plateformes.
PLATFORMS = {
    "agents", "common", "core", "doctor", "gateways", "goal", "integrations",
    "llm", "memory", "modules", "print", "tools", "voice",
    "watchdog",
}

# Etat mesure le 01/09/2026 (Phase 2B, apres extraction du Runtime Governor).
# 303 sites au total, dont 49 vers Core (57 avant l'extraction).
# NE PAS augmenter une valeur pour faire passer le test : c'est le signal que
# l'on ajoute du couplage. Corriger le code, ou justifier explicitement.
BASELINE: dict[str, int] = {
    "agents->common": 10,
    "agents->core": 29,
    "agents->goal": 7,
    "agents->integrations": 2,
    "agents->llm": 4,
    "agents->modules": 26,
    "agents->tools": 4,
    "agents->voice": 2,
    "core->agents": 20,
    "core->common": 17,
    # Phase 2D : 26 -> 22. Retires : task_routes.py (code mort non monte, 2),
    # plan_storage_factory (injection morte, 1), planner_from_goal migre vers
    # GoalClient (1). Voir phase2d-goal-boundary-decision.md.
    # Phase 2E : 22 -> 21 (background_runner.shutdown). Le retrait des routers
    # Goal montes par Core ne bouge PAS ce compteur : le montage passait par
    # importlib.import_module(<chaine>), invisible en AST. Il est verrouille
    # par tests/test_core_does_not_serve_goal.py.
    "core->goal": 21,
    "core->integrations": 1,
    "core->modules": 30,
    "core->tools": 2,
    "doctor->common": 3,
    "goal->agents": 3,
    "goal->common": 21,
    "goal->core": 2,
    "goal->integrations": 2,
    "goal->modules": 3,
    "integrations->common": 2,
    "integrations->core": 1,
    "integrations->tools": 1,
    "llm->common": 5,
    # Phase 2F : llm->core retire (etait 2). Les contrats de providers
    # (models, protocol) vivent desormais dans server/common/providers : le
    # Coeur n a plus a dependre de Core pour parler son propre langage.
    "memory->common": 2,
    "modules->agents": 4,
    "modules->common": 18,
    "modules->core": 14,
    # Couplage volontaire (pas une dette) : DecisionEngine et
    # CapabilityResolver consultent le registre de passerelles (server/gateways)
    # avant de generer un agent/tool pour un domaine externe (mail, contacts,
    # notes, reminders, calendar, repos, docs). Voir decision_engine.py et
    # resolver.py._gateway_connector.
    "modules->gateways": 3,
    "modules->goal": 15,
    "modules->tools": 3,
    "print->common": 2,
    "tools->agents": 1,
    "tools->common": 5,
    "tools->core": 1,
    "tools->integrations": 2,
    "tools->modules": 10,
    "voice->agents": 2,
    "voice->common": 2,
}

# Le cycle constate en Phase 2A. Il doit retrecir, jamais s'etendre.
CYCLE_MEMBERS = {
    "agents", "core", "goal", "integrations", "llm", "modules", "tools", "voice",
}


def _root_package(module: str | None) -> str | None:
    """Plateforme visee par un module importe, en tolerant le prefixe `server.`."""
    if not module:
        return None
    parts = module.split(".")
    if parts[0] == "server" and len(parts) > 1:
        parts = parts[1:]
    return parts[0] if parts[0] in PLATFORMS else None


@pytest.fixture(scope="module")
def edges() -> dict[str, int]:
    """Compte les sites d'import d'une plateforme vers une autre."""
    counts: collections.Counter[str] = collections.Counter()
    for path in SERVER.rglob("*.py"):
        parts = path.relative_to(SERVER).parts
        if "__pycache__" in parts or not parts or parts[0] not in PLATFORMS:
            continue
        source = parts[0]
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:          # import relatif : reste intra-plateforme
                    continue
                target = _root_package(node.module)
            elif isinstance(node, ast.Import):
                target = _root_package(node.names[0].name)
            else:
                continue
            if target and target != source:
                counts[f"{source}->{target}"] += 1
    return dict(counts)


def test_common_is_an_architectural_sink(edges):
    """`common` est le NOYAU PARTAGE : rien n'en sort vers une plateforme.

    Regle posee en Phase 2B : ``plateformes -> common`` est autorise et meme
    souhaite ; ``common -> plateforme`` est interdit, sans exception.

    Une seule violation suffit a recreer un cycle et a faire s'effondrer le plan
    de migration : le noyau ne peut pas dependre de ce qui depend de lui. Ce
    test a effectivement attrape la premiere tentative d'extraction du Runtime
    Governor, qui laissait un ``from core.infrastructure.event_bus import Event``
    (meme confine a TYPE_CHECKING). La dependance a ete remplacee par le
    Protocol structurel ``RuntimeEvent``, defini dans le noyau lui-meme.
    """
    leaking = {e: n for e, n in edges.items() if e.startswith("common->")}
    assert leaking == {}, (
        "server/common ne doit dependre d'aucune plateforme metier, trouve : "
        f"{leaking}"
    )


def test_cycle_does_not_grow(edges):
    """Aucune plateforme supplementaire ne doit entrer dans le cycle."""
    graph = collections.defaultdict(set)
    for edge in edges:
        source, target = edge.split("->")
        graph[source].add(target)

    # Un noeud est dans un cycle s'il est atteignable depuis lui-meme.
    def reaches_itself(start: str) -> bool:
        seen, stack = set(), list(graph.get(start, ()))
        while stack:
            node = stack.pop()
            if node == start:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(graph.get(node, ()))
        return False

    in_cycle = {n for n in set(graph) | {t for ts in graph.values() for t in ts}
                if reaches_itself(n)}
    new = in_cycle - CYCLE_MEMBERS
    assert not new, f"plateformes nouvellement prises dans le cycle : {sorted(new)}"


def test_no_platform_edge_grows(edges):
    """Cliquet : aucune arete vers une PLATEFORME ne gagne de sites.

    Les aretes ``* -> common`` sont volontairement exclues : deplacer une
    primitive de Core vers le noyau fait mecaniquement monter ``x -> common``
    en faisant baisser ``x -> core``. C'est le mouvement recherche, pas une
    regression. Ce qui est verrouille, c'est le couplage entre plateformes
    metier — et la trajectoire de ``* -> core`` (test suivant).
    """
    grown = {
        edge: (BASELINE.get(edge, 0), count)
        for edge, count in edges.items()
        if not edge.endswith("->common") and count > BASELINE.get(edge, 0)
    }
    assert not grown, (
        "couplage inter-plateformes en hausse (arete: reference -> mesure) : "
        f"{grown}. Corriger le code plutot que la reference."
    )


def test_baseline_has_no_stale_entry(edges):
    """Une arete tombee a zero doit sortir de BASELINE, pour que le cliquet morde."""
    stale = sorted(e for e in BASELINE if e not in edges)
    assert not stale, f"aretes disparues, a retirer de BASELINE : {stale}"


# Sites d'import pointant vers Core depuis une autre plateforme.
# Phase 2A : 57. Phase 2B apres extraction du Runtime Governor : 49.
# Phase 2D : 42 (facades du noyau en Phase 2C + suppression de code mort).
# Phase 2F : 40 (contrats de providers extraits vers le noyau).
# Cible du plan de migration : ~22 une fois tout le noyau extrait.
MAX_IMPORTS_INTO_CORE = 40


def test_dependencies_on_core_do_not_grow(edges):
    """Metrique centrale de la Phase 2B : le couplage vers Core doit decroitre.

    Faire baisser ce chiffre est l'objet meme du chantier ; le faire monter
    signifie qu'on a rajoute de la logique dans Core ou un appelant de plus.
    Quand il baisse, abaisser MAX_IMPORTS_INTO_CORE dans la foulee.
    """
    into_core = sum(n for e, n in edges.items() if e.endswith("->core"))

    assert into_core <= MAX_IMPORTS_INTO_CORE, (
        f"{into_core} imports vers Core, reference {MAX_IMPORTS_INTO_CORE}. "
        "Extraire vers le noyau plutot que relever la reference."
    )
