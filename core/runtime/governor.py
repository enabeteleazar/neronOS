"""TEMPORARY COMPATIBILITY SHIM — Phase 2B.

Destination : ``server.common.runtime.governor``.

Le Runtime Governor est une primitive de NOYAU : il autorise les commandes
systeme pour tout le monde (Core, Goal, agents, modules, outils). Il ne relevait
donc pas de Core. Il a ete extrait vers le noyau partage.

Ce module ne subsiste que le temps de migrer les appelants restants — au premier
chef ceux du sous-module ``goal``, qu on ne modifie pas depuis le depot parent.

Le reexport partage l objet module d origine : il n existe qu UN seul singleton
``_governor``, quel que soit le chemin d import emprunte.

A supprimer quand ``git grep "core.runtime.governor"`` ne renvoie plus rien.
"""

from server.common.runtime.governor import (  # noqa: F401
    RuntimeEvent,
    RuntimeGovernor,
    RuntimePolicy,
    get_runtime_governor,
    handle_self_model_governor_event,
)

__all__ = [
    "RuntimeEvent",
    "RuntimeGovernor",
    "RuntimePolicy",
    "get_runtime_governor",
    "handle_self_model_governor_event",
]
