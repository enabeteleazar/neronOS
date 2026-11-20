"""Redirection de compatibilité : le bac à sable vit dans le noyau partagé.

Implémentation : server/common/runtime/sandbox/agent_sandbox.py. Le module est
aliasé (et non réexporté) : `core.runtime.sandbox.agent_sandbox` et
`server.common.runtime.sandbox.agent_sandbox` désignent le MÊME objet module,
donc la même configuration et les mêmes points de remplacement en test.
"""
import sys

from server.common.runtime.sandbox import agent_sandbox as _impl

sys.modules[__name__] = _impl
