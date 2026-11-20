from modules.cognitive.critic_engine import CriticEngine


def test_orchestrated_plan_has_deduplicated_risks_without_false_approval_warning(
    monkeypatch,
):
    monkeypatch.setattr(CriticEngine, "save_evaluation", lambda *_args: None)
    plan = {
        "orchestrated": True,
        "approved": False,
        "approval_required": False,
        "steps": [
            {"agent": "agent_creator", "action": "define_agent"},
            {"agent": "agent_creator", "action": "create_skeleton"},
        ],
    }

    result = CriticEngine().evaluate_plan(plan)

    assert result["risks"].count("Agent pouvant produire du code : agent_creator.") == 1
    assert "Le plan n'est pas approuvé." not in result["risks"]
