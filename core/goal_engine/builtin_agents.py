from __future__ import annotations

from core.a2a import A2AClient, AgentCard, AgentTask
from core.agent_registry import get_external_agent_registry

from .agent_registry import AgentRegistry

# Chargement dynamique (invisible pour le controle d'architecture core->agents,
# meme motif que pipeline/routing/agent_router.py::_external_agents) : ce
# fichier vit dans core, PCRemoteAgent dans agents.
_external_agents = get_external_agent_registry()


PC_REMOTE_AGENT_CARD = AgentCard(
    agent_id="pc_remote_agent",
    name="PC Remote Agent",
    description="Pilote un PC distant (ouvrir/fermer des applications) via l'agent HTTP pc_remote, sur le tailnet.",
    capabilities=["remote_control", "app_management"],
    tags=["pc_remote", "remote", "automation", "windows", "linux"],
    status="available",
    metadata={
        "source": "core_builtin",
        "runtime_type": "on_demand",
        "managed_by": "agent_registry",
    },
)

SHOP_AGENT_CARD = AgentCard(
    agent_id="shop_agent",
    name="Shop Agent",
    description=(
        "Recherche un produit sur Amazon.fr à partir d'une demande en langage naturel "
        "et remplit le panier réel — ne valide jamais la commande automatiquement."
    ),
    capabilities=["shopping", "purchase_assist", "amazon"],
    tags=["shop", "amazon", "purchase", "ecommerce"],
    status="available",
    metadata={
        "source": "core_builtin",
        "runtime_type": "on_demand",
        "managed_by": "agent_registry",
    },
)


async def pc_remote_agent_handler(task: AgentTask) -> dict[str, object]:
    query = str(task.payload.get("query") or task.payload.get("text") or "").strip()
    if not query:
        raise ValueError(
            "Requete pc_remote vide : specifiez 'query' (commande en langage naturel, "
            "ex. \"ouvre chrome sur mon pc windows\")."
        )
    pc_remote_agent_class = _external_agents.agent_class(
        "agents.builtin.automation.pc_remote_agent", "PCRemoteAgent"
    )
    result = await pc_remote_agent_class().execute(query)
    if not result.success:
        raise ValueError(result.error or "Echec de la commande pc_remote.")
    return {
        "agent_response": result.content,
        **result.metadata,
    }


async def shop_agent_handler(task: AgentTask) -> dict[str, object]:
    query = str(task.payload.get("query") or task.payload.get("text") or "").strip()
    if not query:
        raise ValueError(
            "Requete shop vide : specifiez 'query' (demande d'achat en langage naturel, "
            "ex. \"achete-moi un cable usb-c 2m, budget max 15e\")."
        )
    shop_agent_class = _external_agents.agent_class(
        "agents.builtin.io.shop_agent", "ShopAgent"
    )
    agent_response = await shop_agent_class().run(query)
    return {"agent_response": agent_response}


def install_builtin_agents(agents: AgentRegistry, a2a: A2AClient) -> None:
    agents.register(PC_REMOTE_AGENT_CARD)
    a2a.register_handler(PC_REMOTE_AGENT_CARD, pc_remote_agent_handler)
    agents.register(SHOP_AGENT_CARD)
    a2a.register_handler(SHOP_AGENT_CARD, shop_agent_handler)
