import atexit
import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("NERON_API_KEY", "test-api-key")
os.environ["NERON_SANDBOX_BACKEND"] = "python"
os.environ["NERON_SANDBOX_SYSTEMD_USE_SUDO"] = "false"
os.environ.setdefault("NERON_TASK_WORKER_ENABLED", "false")
# Classifieur CamemBERT coupé par défaut : sinon chaque session de tests
# chargerait (ou téléchargerait, ~440 Mo) le modèle. Couvert par
# tests/test_intent_classifier_ml.py (marqueur slow), qui le réactive.
os.environ.setdefault("NERON_INTENT_CLASSIFIER", "0")

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="neron-pytest-"))
_TEST_DATA = _TEST_ROOT / "data"
_TEST_WORKSPACE = _TEST_ROOT / "workspace"
_TEST_MEMORY = _TEST_ROOT / "memory"

os.environ["NERON_TEST_ROOT"] = str(_TEST_ROOT)
os.environ["NERON_DATA_DIR"] = str(_TEST_DATA)
os.environ["NERON_WORKSPACE"] = str(_TEST_WORKSPACE)
os.environ["NERON_MEMORY_DIR"] = str(_TEST_MEMORY)
os.environ["NERON_STATE_DB"] = str(_TEST_DATA / "neron_state.sqlite3")
os.environ["NERON_GENERATED_AGENTS_DIR"] = str(
    _TEST_DATA / "generated_agents"
)
os.environ["NERON_PROJECTS_PATH"] = str(_TEST_DATA / "projects.json")
os.environ["NERON_TASKS_PATH"] = str(_TEST_DATA / "tasks.json")
os.environ["NERON_PLANS_PATH"] = str(_TEST_DATA / "plans.jsonl")
os.environ["NERON_GOALS_PATH"] = str(_TEST_DATA / "goals_state.json")
os.environ["NERON_CRITIC_HISTORY_PATH"] = str(
    _TEST_DATA / "critic_history.jsonl"
)
os.environ["NERON_ACTION_HISTORY_PATH"] = str(
    _TEST_DATA / "action_history.jsonl"
)
os.environ["NERON_SELF_MODEL_STATE_PATH"] = str(
    _TEST_DATA / "self_model_state.json"
)
os.environ["NERON_WORLD_MODEL_STATE_PATH"] = str(
    _TEST_DATA / "world_model_state.json"
)
os.environ["NERON_EVOLUTION_STATE_PATH"] = str(
    _TEST_DATA / "evolution_state.json"
)
os.environ["NERON_AGENT_PROPOSALS_PATH"] = str(
    _TEST_DATA / "agent_creator_proposals.jsonl"
)

atexit.register(shutil.rmtree, _TEST_ROOT, ignore_errors=True)

# Garde-fou : sans surcharge, ObliviaProvider vise son defaut
# http://127.0.1.4:8040 — la memoire de PRODUCTION. Un test qui memorise
# ecrirait dans les vrais souvenirs. On pointe vers un port ferme : les
# tests qui passent par tests/_memory_stack.py sont branches en process par
# transport ASGI et ne s'en servent pas ; les autres echouent vite et fort
# au lieu de polluer la production en silence.
os.environ["NERON_MEMORY_URL"] = "http://127.0.0.1:9"
