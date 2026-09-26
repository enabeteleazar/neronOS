"""Coherence des unites systemd versionnees dans system/deploy/systemd.

Ce fichier testait l architecture pre-template (neron-core.service,
neron-llm.service, neron-web.service, install_systemd.sh, racine /etc/neron
puis /srv/homelab/server-1/neronOS). Aucun de ces fichiers n existe plus : les
services metier passent tous par le template neron@.service et le point
d entree unique `python -m common.serve <noeud>`.

Les assertions ci-dessous portent sur l architecture reellement deployee.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SYSTEMD_DIR = ROOT / "system" / "deploy" / "systemd"
INSTALL_SCRIPT = ROOT / "system" / "deploy" / "install.sh"
SERVER_PLAN = ROOT / "neron.server.yaml"

NERON_ROOT = "/etc/neronOS"

# Services instancies via le template neron@.service. Chaque nom doit exister
# comme noeud dans neron.server.yaml, sinon common.serve refuse de demarrer.
TEMPLATED_SERVICES = (
    "core", "llm", "memory", "goal", "doctor",
    "voice", "print", "gateways",
)

# Unites autonomes (boucles et sidecars), avec le module python qu elles lancent.
# neron-self-model-loop.service a ete retiree en Phase 2B : Core est desormais
# l unique ecrivain du SelfModel et persiste lui-meme son cache de redemarrage.
STANDALONE_UNITS = {
    "neron-cognitive-loop.service": "modules.autonomous.run_cognitive_loop",
    "neron-world-model-loop.service": "modules.world_model.world_model_loop",
    "neron-homeassistant-registry.service": "integrations.homeassistant.registry_runner",
}


def _read(name: str) -> str:
    return (SYSTEMD_DIR / name).read_text(encoding="utf-8")


def test_template_unit_uses_common_serve_entrypoint():
    content = _read("neron@.service")

    assert f"WorkingDirectory={NERON_ROOT}/server" in content
    assert f"ExecStart={NERON_ROOT}/venv/bin/python -m common.serve %i" in content
    # La topologie vient du plan, jamais d un port code en dur dans l unite.
    assert "--port" not in content
    # L environnement commun est obligatoire ; les secrets restent optionnels.
    assert f"EnvironmentFile={NERON_ROOT}/env/common.env" in content
    assert f"EnvironmentFile=-{NERON_ROOT}/secrets.env" in content


def test_target_wants_every_templated_service():
    wants = set(re.findall(r"^Wants=(neron@[\w-]+\.service)$",
                           _read("neron.target"), re.MULTILINE))

    expected = {f"neron@{name}.service" for name in TEMPLATED_SERVICES}
    assert expected <= wants, f"absents de neron.target : {sorted(expected - wants)}"


@pytest.mark.parametrize("service", TEMPLATED_SERVICES)
def test_every_templated_service_has_a_node_in_the_server_plan(service):
    nodes = yaml.safe_load(SERVER_PLAN.read_text(encoding="utf-8"))["nodes"]

    assert service in nodes, f"noeud '{service}' absent de neron.server.yaml"
    node = nodes[service]
    assert node.get("host"), f"noeud '{service}' sans host"
    has_port = "port" in node or any(k.endswith("_port") for k in node)
    assert has_port, f"noeud '{service}' sans port"


@pytest.mark.parametrize("unit,module", STANDALONE_UNITS.items())
def test_standalone_units_use_current_runtime_paths(unit, module):
    content = _read(unit)

    assert f"WorkingDirectory={NERON_ROOT}/server" in content
    assert f"Environment=NERON_ROOT={NERON_ROOT}" in content
    assert f"Environment=NERON_CONFIG={NERON_ROOT}/neron.yaml" in content
    assert f"ExecStart={NERON_ROOT}/venv/bin/python -m {module}" in content


def test_timers_reference_units_and_scripts_that_exist():
    for timer in SYSTEMD_DIR.glob("*.timer"):
        content = timer.read_text(encoding="utf-8")

        unit = re.search(r"^Unit=(.+)$", content, re.MULTILINE)
        name = unit.group(1).strip() if unit else timer.with_suffix(".service").name
        service = SYSTEMD_DIR / name
        assert service.exists(), f"{timer.name} declenche {name}, absent du depot"

        exec_start = re.search(r"^ExecStart=(\S+)", service.read_text(encoding="utf-8"),
                               re.MULTILINE)
        assert exec_start, f"{name} sans ExecStart"
        target = Path(exec_start.group(1))
        if target.is_absolute() and str(target).startswith(NERON_ROOT):
            relative = ROOT / target.relative_to(NERON_ROOT)
            assert relative.exists(), f"{name} lance {target}, absent du depot"


def test_install_script_covers_every_versioned_unit():
    script = INSTALL_SCRIPT.read_text(encoding="utf-8")

    # install.sh boucle sur systemd/* : toute unite deposee la est installee.
    assert 'for u in "$HERE"/systemd/*' in script
    assert '/etc/systemd/system/$(basename "$u")' in script
    assert f'{NERON_ROOT}/env/common.env' in script


def test_no_legacy_unit_survives_in_the_deploy_directory():
    legacy = {
        "neron-core.service", "neron-llm.service", "neron-goal.service",
        "neron-memory.service", "neron-voice.service", "neron-doctor.service",
        "neron-web.service", "neron-watchdog.service", "neron.service",
        "neronOS.service",
    }
    present = {p.name for p in SYSTEMD_DIR.iterdir()}

    assert not (legacy & present), f"unites pre-template encore presentes : {legacy & present}"
