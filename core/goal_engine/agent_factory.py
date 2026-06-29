from __future__ import annotations

import re
import ast
import asyncio
import json
import subprocess
import sys
import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import GoalAnalysis
from core.providers.models import ProviderRequest
from core.providers.registry import ProviderRegistry


class ModuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: str
    capabilities: list[str] = Field(default_factory=list)
    provider_type: Literal["memory", "llm", "a2a", "generic"] = "generic"


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: str
    capabilities: list[str] = Field(default_factory=list)
    modules: list[ModuleSpec] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    validation_task: str = ""


class AgentCreationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_analysis: GoalAnalysis
    preferred_name: str | None = None


class AgentCreationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["planned"] = "planned"
    spec: AgentSpec
    rationale: str
    files_created: bool = False
    runtime_registered: bool = False


class AgentCreationArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_file: str
    test_file: str
    manifest_file: str
    model: str
    test_passed: bool


class AgentFactory:
    """Produces reviewable specifications; it never writes or registers agents."""

    def create_spec(self, request: AgentCreationRequest) -> AgentSpec:
        analysis = request.goal_analysis
        capabilities = list(dict.fromkeys(analysis.required_capabilities or ["generic"]))
        name = request.preferred_name or self._proposed_name(capabilities)
        modules = [
            ModuleSpec(
                name=f"{capability}_module",
                role=f"Fournir la capacité {capability}.",
                capabilities=[capability],
                provider_type=self._provider_type(capability),
            )
            for capability in capabilities
        ]
        return AgentSpec(
            name=name,
            role=f"Exécuter l'objectif : {analysis.summary}",
            capabilities=capabilities,
            modules=modules,
            permissions=["a2a.task.execute", "provider.read"],
            risks=[
                "Résultat incomplet si une capacité requise est indisponible.",
                "Exécution à maintenir dans les limites du sandbox.",
            ],
            tests=[
                "validation_agent_card",
                "capabilities_contract",
                "a2a_task_execution",
                "sandbox_permissions",
            ],
            validation_task=(
                "Météo actuelle à Paris"
                if "weather" in capabilities
                else analysis.objective
            ),
        )

    def create_plan(self, request: AgentCreationRequest) -> AgentCreationPlan:
        return AgentCreationPlan(
            spec=self.create_spec(request),
            rationale="Aucun agent compatible n'est enregistré; une spécification contrôlée est proposée.",
        )

    async def generate_supervised(
        self,
        plan: AgentCreationPlan,
        providers: ProviderRegistry,
        *,
        generated_dir: Path = Path("/etc/neron/workspace/generated_candidates/agents"),
        tests_dir: Path = Path("/etc/neron/workspace/generated_candidates/tests"),
    ) -> AgentCreationArtifacts:
        llm_infos = providers.by_type("llm")
        llm = providers.get(llm_infos[0].name) if llm_infos else None
        if llm is None:
            raise RuntimeError("LLMProvider unavailable for supervised generation")
        spec = plan.spec
        prompt = self._generation_prompt(spec)
        result: dict[str, Any] = {}
        source = ""
        validation_error: Exception | None = None
        for attempt in range(2):
            response = await llm.execute(ProviderRequest(
                action="generate",
                payload={
                    "task_type": "agent",
                    "model_preference": "Qwen2.5-Coder:1.5b",
                    "prompt": prompt,
                },
            ))
            result = response.result if isinstance(response.result, dict) else {}
            source = _strip_code_fence(str(result.get("text") or ""))
            if response.error or not source:
                raise RuntimeError(response.error or result.get("warning") or "LLM generated empty source")
            source = self._normalize_contract(source, spec)
            try:
                self._validate_source(source, spec)
                validation_error = None
                break
            except (SyntaxError, ValueError) as exc:
                validation_error = exc
                if attempt == 0:
                    prompt = self._repair_prompt(spec, source, str(exc))
        if validation_error is not None:
            raise validation_error

        generated_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)
        agent_file = generated_dir / f"{spec.name}.py"
        test_file = tests_dir / f"test_{spec.name}.py"
        manifest_file = generated_dir / f"{spec.name}.manifest.json"
        source = source.rstrip() + "\n\nAGENT_SPEC = " + repr(self._runtime_spec(spec)) + "\n"
        agent_file.write_text(source, encoding="utf-8")
        test_file.write_text(self._test_source(agent_file, spec), encoding="utf-8")
        manifest_file.write_text(
            json.dumps(self._manifest(spec, result), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return AgentCreationArtifacts(
            agent_file=str(agent_file),
            test_file=str(test_file),
            manifest_file=str(manifest_file),
            model=str(result.get("model") or ""),
            test_passed=False,
        )

    @staticmethod
    def existing_candidate(
        plan: AgentCreationPlan,
        *,
        generated_dir: Path = Path("/etc/neron/workspace/generated_candidates/agents"),
        tests_dir: Path = Path("/etc/neron/workspace/generated_candidates/tests"),
    ) -> AgentCreationArtifacts | None:
        agent_file = generated_dir / f"{plan.spec.name}.py"
        test_file = tests_dir / f"test_{plan.spec.name}.py"
        manifest_file = generated_dir / f"{plan.spec.name}.manifest.json"
        if not all(path.is_file() for path in (agent_file, test_file, manifest_file)):
            return None
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        source = agent_file.read_text(encoding="utf-8")
        body = source.split("\nAGENT_SPEC =", 1)[0].rstrip()
        body = AgentFactory._normalize_contract(body, plan.spec)
        AgentFactory._validate_source(body, plan.spec)
        agent_file.write_text(
            body + "\n\nAGENT_SPEC = " + repr(AgentFactory._runtime_spec(plan.spec)) + "\n",
            encoding="utf-8",
        )
        test_file.write_text(
            AgentFactory._test_source(agent_file, plan.spec),
            encoding="utf-8",
        )
        return AgentCreationArtifacts(
            agent_file=str(agent_file),
            test_file=str(test_file),
            manifest_file=str(manifest_file),
            model=str(manifest.get("generation", {}).get("model") or ""),
            test_passed=False,
        )

    async def repair_supervised(
        self,
        artifacts: AgentCreationArtifacts,
        plan: AgentCreationPlan,
        providers: ProviderRegistry,
        error: str,
    ) -> AgentCreationArtifacts:
        llm_infos = providers.by_type("llm")
        llm = providers.get(llm_infos[0].name) if llm_infos else None
        if llm is None:
            raise RuntimeError("LLMProvider unavailable for supervised repair")
        source = Path(artifacts.agent_file).read_text(encoding="utf-8")
        source = source.split("\nAGENT_SPEC =", 1)[0].rstrip()
        response = await llm.execute(ProviderRequest(
            action="generate",
            payload={
                "task_type": "agent",
                "model_preference": "Qwen2.5-Coder:1.5b",
                "prompt": self._repair_prompt(plan.spec, source, error[-400:]),
            },
        ))
        result = response.result if isinstance(response.result, dict) else {}
        repaired = self._normalize_contract(
            _strip_code_fence(str(result.get("text") or "")),
            plan.spec,
        )
        if response.error or not repaired:
            raise RuntimeError(response.error or result.get("warning") or "LLM repair returned empty source")
        self._validate_source(repaired, plan.spec)
        repaired = repaired.rstrip() + "\n\nAGENT_SPEC = " + repr(self._runtime_spec(plan.spec)) + "\n"
        Path(artifacts.agent_file).write_text(repaired, encoding="utf-8")
        artifacts.model = str(result.get("model") or artifacts.model)
        return artifacts

    @staticmethod
    def promote(
        artifacts: AgentCreationArtifacts,
        *,
        generated_dir: Path = Path("/etc/neron/data/generated_agents"),
        tests_dir: Path = Path("/etc/neron/data/generated_agent_tests"),
    ) -> AgentCreationArtifacts:
        generated_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)
        source_agent = Path(artifacts.agent_file)
        source_test = Path(artifacts.test_file)
        source_manifest = Path(artifacts.manifest_file)
        agent_file = generated_dir / source_agent.name
        test_file = tests_dir / source_test.name
        manifest_file = generated_dir / source_manifest.name
        shutil.copy2(source_agent, agent_file)
        shutil.copy2(source_manifest, manifest_file)
        manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
        spec = AgentSpec.model_validate(manifest["agent"])
        test_file.write_text(
            AgentFactory._test_source(agent_file, spec),
            encoding="utf-8",
        )
        source_agent.unlink(missing_ok=True)
        source_test.unlink(missing_ok=True)
        source_manifest.unlink(missing_ok=True)
        for cache_dir in {
            source_agent.parent / "__pycache__",
            source_test.parent / "__pycache__",
        }:
            shutil.rmtree(cache_dir, ignore_errors=True)
        artifacts.agent_file = str(agent_file)
        artifacts.test_file = str(test_file)
        artifacts.manifest_file = str(manifest_file)
        return artifacts

    async def validate_artifacts(
        self,
        artifacts: AgentCreationArtifacts,
        *,
        timeout: float = 30.0,
    ) -> AgentCreationArtifacts:
        completed = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "pytest", "-q", artifacts.test_file],
            text=True,
            capture_output=True,
            timeout=timeout,
            cwd="/etc/neron",
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "generated agent tests failed: "
                + (completed.stdout + completed.stderr)[-2000:]
            )
        artifacts.test_passed = True
        return artifacts

    @staticmethod
    def _generation_prompt(spec: AgentSpec) -> str:
        return (
            "Generate complete executable Python source, never placeholders. "
            f"Define class Agent with name={spec.name!r} and capabilities={spec.capabilities!r}. "
            "Define async execute(self, text: str = '', context: dict | None = None) -> dict. "
            "Read normalized real weather from context['weather']; do not perform network or file IO. "
            "Return status='ok', agent name, source from weather, temperature_c, weather_code, "
            "and a non-empty French response containing location and temperature. "
            "Allowed code: pure Python only, no imports are necessary. "
            "Output only Python source without markdown or explanations."
        )

    @staticmethod
    def _repair_prompt(spec: AgentSpec, source: str, error: str) -> str:
        return (
            "Repair the following generated Python agent. Output only the complete corrected source. "
            f"Validation error: {error}. "
            "Critical rule: weather data is already supplied in context['weather']; "
            "remove all HTTP, requests, urllib, network and file access. "
            "context['weather'] is already a Python dict: never call json.loads on it. "
            f"Agent.name must be {spec.name!r}; execute must remain async and return status ok, "
            "source, temperature_c, weather_code, and key 'response' containing French text "
            "with location and temperature. Read temperature_c, not temp_c.\n"
            "SOURCE TO REPAIR:\n"
            + source
        )

    @staticmethod
    def _validate_source(source: str, spec: AgentSpec) -> None:
        tree = ast.parse(source)
        forbidden_roots = {"requests", "urllib", "httpx", "socket", "subprocess", "os"}
        forbidden_names = {"open", "eval", "exec", "compile", "__import__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in forbidden_names:
                    raise ValueError(f"generated agent call is forbidden: {node.func.id}")
                if isinstance(node.func, ast.Attribute):
                    root = node.func.value
                    while isinstance(root, ast.Attribute):
                        root = root.value
                    if isinstance(root, ast.Name) and root.id in forbidden_roots:
                        raise ValueError(
                            f"generated agent external call is forbidden: "
                            f"{root.id}.{node.func.attr}"
                        )
        if any(isinstance(node, (ast.While, ast.For, ast.AsyncFor)) for node in ast.walk(tree)):
            raise ValueError("generated agent loops are forbidden")
        agent = next(
            (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Agent"),
            None,
        )
        if agent is None:
            raise ValueError("generated agent has no Agent class")
        execute = next(
            (node for node in agent.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute"),
            None,
        )
        if execute is None:
            raise ValueError("generated agent has no async execute")
        assignments = {
            target.id: ast.literal_eval(node.value)
            for node in agent.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
            and target.id in {"name", "capabilities"}
        }
        if assignments.get("name") != spec.name:
            raise ValueError("generated agent name does not match AgentSpec")

    @staticmethod
    def _normalize_contract(source: str, spec: AgentSpec) -> str:
        source, name_count = re.subn(
            r"(?m)^(\s{4})name\s*=\s*.+$",
            rf"\1name = {spec.name!r}",
            source,
            count=1,
        )
        source, capability_count = re.subn(
            r"(?m)^(\s{4})capabilities\s*=\s*.+$",
            rf"\1capabilities = {spec.capabilities!r}",
            source,
            count=1,
        )
        additions = []
        if name_count == 0:
            additions.append(f"    name = {spec.name!r}")
        if capability_count == 0:
            additions.append(f"    capabilities = {spec.capabilities!r}")
        if additions:
            source = source.replace(
                "class Agent:",
                "class Agent:\n" + "\n".join(additions),
                1,
            )
        if "weather" in spec.capabilities:
            source = re.sub(
                r"(?m)^(\s*)async def execute\(self,.*context.*\)\s*->\s*dict:$",
                r"\1async def execute(self, text: str = '', execution_context=None) -> dict:",
                source,
                count=1,
            )
            signature = "async def execute(self, text: str = '', execution_context=None) -> dict:"
            if signature in source and "context = execution_context.context" not in source:
                source = source.replace(
                    signature,
                    signature
                    + "\n        context = execution_context.context if execution_context else {}",
                    1,
                )
            source = re.sub(
                r"(?m)^(\s*)['\"]source['\"]\s*:\s*.+,$",
                r"\1'source': context.get('weather', {}).get('source', ''),",
                source,
                count=1,
            )
            source = re.sub(
                r"(?m)^(\s*)['\"]french_response['\"]\s*:",
                r"\1'response':",
                source,
                count=1,
            )
        return source

    @staticmethod
    def _runtime_spec(spec: AgentSpec) -> dict[str, Any]:
        return {
            "name": spec.name,
            "description": spec.role,
            "capabilities": spec.capabilities,
            "tags": ["generated", "supervised", *spec.capabilities],
            "validation_task": spec.validation_task,
        }

    @staticmethod
    def _manifest(spec: AgentSpec, llm_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "agent": spec.model_dump(mode="json"),
            "generation": {
                "provider": "llm",
                "model": llm_result.get("model"),
                "supervised": True,
            },
        }

    @staticmethod
    def _test_source(agent_file: Path, spec: AgentSpec) -> str:
        return (
            "import asyncio\nimport importlib.util\n\n"
            f"AGENT_FILE = {str(agent_file)!r}\n\n"
            "def test_generated_agent_contract():\n"
            "    module_spec = importlib.util.spec_from_file_location('generated_weather_agent', AGENT_FILE)\n"
            "    module = importlib.util.module_from_spec(module_spec)\n"
            "    module_spec.loader.exec_module(module)\n"
            "    execution_context = type('Context', (), {'context': {'weather': {"
            "'location': 'Paris', 'temperature_c': 20.5, 'weather_code': 1, "
            "'source': 'open-meteo'}}})()\n"
            "    result = asyncio.run(module.Agent().execute("
            "'Météo actuelle à Paris', execution_context=execution_context))\n"
            "    assert result['status'] == 'ok'\n"
            "    assert result['source'] == 'open-meteo'\n"
            "    assert 'Paris' in result['response']\n"
            "    assert '20.5' in result['response']\n"
        )

    @staticmethod
    def _proposed_name(capabilities: list[str]) -> str:
        preferred = (
            "weather"
            if "weather" in capabilities
            else next(
            (
                capability
                for capability in capabilities
                if capability not in {"agent_creation", "planning", "generic"}
            ),
            capabilities[0],
            )
        )
        base = re.sub(r"[^a-z0-9]+", "_", preferred.lower()).strip("_")
        return f"{base or 'generic'}_agent"

    @staticmethod
    def _provider_type(capability: str) -> str:
        if capability in {"memory", "remember", "recall", "search"}:
            return "memory"
        if capability in {"reasoning", "generation", "planning"}:
            return "llm"
        return "generic"


agent_factory = AgentFactory()


def _strip_code_fence(value: str) -> str:
    text = value.strip()
    fenced = re.search(r"```(?:python)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1)
    elif "class Agent:" in text:
        text = text[text.index("class Agent:") :]
    return text.strip()
