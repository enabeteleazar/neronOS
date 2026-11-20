"""Bac à sable du code généré : primitive du noyau partagé.

Utilisé par les agents (exécution, construction, mise à jour), les outils
générés et la validation métier. Déplacé depuis core/runtime/sandbox (qui en
garde une redirection) : comme le Runtime Governor en phase 2B, c'est une
primitive de noyau, pas une capacité du Core.
"""
from server.common.runtime.sandbox.agent_sandbox import AgentSandbox, sensitive_paths

__all__ = ["AgentSandbox", "sensitive_paths"]
