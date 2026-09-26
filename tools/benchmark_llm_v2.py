#!/usr/bin/env python3
"""Benchmark V2 — sweep de `ollama_num_predict` pour NeronLLM.

Objectif : mesurer combien de latence est due a la longueur de generation
non plafonnee (`llm.ollama_num_predict: 0` en production), et si une
limite (32/48/64/96/128) offre un meilleur compromis vitesse/qualite.

Reutilise tools/benchmark_llm.py (jeu de tests, appel Ollama direct,
detection environnement) plutot que de dupliquer un systeme parallele.

Niveau A (Ollama direct) : identique a V1, `--num-predict` transmis tel
quel a /api/generate (0 = pas de plafond, cf run_ollama_direct).

Niveau B (NeronLLM reel) :
  - num_predict=0  -> appelle le service de production reel en HTTP
    (/llm/generate), EXACTEMENT comme en V1 : c'est la config actuellement
    deployee, aucune raison de la simuler autrement.
  - num_predict>0  -> POST /llm/generate n'a pas de champ num_predict
    (verifie dans server/llm/core/types.py — GenerateRequest ne l'expose
    pas ; c'est fixe a la construction de OllamaProvider depuis
    neron.yaml). Impossible de le surcharger par requete sans modifier la
    prod. Solution retenue (la moins intrusive trouvee) : instancier le
    meme LLMManager dans un sous-processus jetable, pointe via la variable
    d'environnement NERON_CONFIG (deja supportee par server/common/paths.py)
    vers une copie temporaire de neron.yaml ou seul ollama_num_predict
    differe. Le neron.yaml reel et neron@llm.service ne sont JAMAIS
    modifies, ni redemarres. Chaque fichier temporaire est supprime
    immediatement apres usage (cf `run_inprocess_b`).

Usage :
    python tools/benchmark_llm_v2.py
    python tools/benchmark_llm_v2.py --models llama3.2:1b --num-predicts 0,32,64
    python tools/benchmark_llm_v2.py --level a --runs 3
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_llm import (  # noqa: E402
    TESTS,
    RESULTS_DIR,
    check_ollama_running,
    get_hardware_info,
    get_installed_models,
    get_model_details,
    resolve_model_name,
    unload_model,
    run_ollama_direct,
    run_neron_llm,
)

NERON_ROOT = Path(__file__).resolve().parents[1]
NERON_YAML_PATH = NERON_ROOT / "neron.yaml"
TMP_CONFIG_DIR = Path(tempfile.gettempdir()) / "neron_bench_v2_configs"
INPROCESS_PROBE = Path(__file__).resolve().parent / "llm_v2_inprocess_probe.py"

DEFAULT_MODELS = ["llama3.2:1b", "qwen2.5:1.5b"]
DEFAULT_NUM_PREDICTS = [0, 32, 48, 64, 96, 128]


# ── Config temporaire (jamais neron.yaml de prod) ─────────────────────────

def make_temp_config(num_predict: int) -> Path:
    TMP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(NERON_YAML_PATH.read_text())
    cfg["llm"]["ollama_num_predict"] = num_predict
    fd, path_str = tempfile.mkstemp(prefix=f"neron_np{num_predict}_", suffix=".yaml", dir=TMP_CONFIG_DIR)
    with os.fdopen(fd, "w") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)
    return Path(path_str)


def cleanup_temp_configs() -> None:
    if not TMP_CONFIG_DIR.exists():
        return
    for f in TMP_CONFIG_DIR.glob("*"):
        f.unlink(missing_ok=True)
    try:
        TMP_CONFIG_DIR.rmdir()
    except OSError:
        pass


def run_inprocess_b(model: str, num_predict: int, runs: int, warmup: int,
                     timeout_s: float, output_path: Path) -> None:
    tmp_cfg = make_temp_config(num_predict)
    env = dict(os.environ)
    env["NERON_CONFIG"] = str(tmp_cfg)
    cmd = [
        sys.executable, str(INPROCESS_PROBE),
        "--model", model, "--num-predict", str(num_predict),
        "--runs", str(runs), "--warmup", str(warmup),
        "--timeout", str(timeout_s), "--output", str(output_path),
    ]
    subprocess_timeout = timeout_s * len(TESTS) * (runs + warmup) + 180
    try:
        subprocess.run(cmd, env=env, timeout=subprocess_timeout)
    except subprocess.TimeoutExpired:
        print(f"    [B-inprocess np={num_predict}] ABANDON — sous-processus > {subprocess_timeout:.0f}s")
    finally:
        tmp_cfg.unlink(missing_ok=True)


# ── Garde-fou sante systeme (lecon du V1 : degradation en fin de run) ────

def system_health() -> tuple[float, int | None]:
    load1, _, _ = os.getloadavg()
    hw = get_hardware_info()
    return load1, hw["ram_available_mb"]


# ── Agregation ─────────────────────────────────────────────────────────

def aggregate_v2(raw_path: Path) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    with open(raw_path) as f:
        for line in f:
            r = json.loads(line)
            if r.get("is_warmup"):
                continue
            key = (r["model"], r["level"], r.get("num_predict"), r["test_id"])
            groups[key].append(r)

    summary = []
    for (model, level, np_val, test_id), recs in groups.items():
        ok = [r for r in recs if not r.get("error")]
        n_total = len(recs)
        n_ok = len(ok)

        def stat(field, fn):
            vals = [r[field] for r in ok if r.get(field) is not None]
            return fn(vals) if vals else None

        eval_count_mean = stat("eval_count", statistics.mean)
        eval_dur_mean = stat("eval_duration_s", statistics.mean)
        gen_tps = (eval_count_mean / eval_dur_mean) if (eval_count_mean and eval_dur_mean) else None
        resp_word_counts = [len((r.get("response_text") or "").split()) for r in ok]

        summary.append({
            "model": model,
            "level": level,
            "num_predict": np_val,
            "test_id": test_id,
            "n_runs": n_total,
            "n_success": n_ok,
            "stability_pct": round(100 * n_ok / n_total, 1) if n_total else None,
            "wall_duration_s_mean": stat("wall_duration_s", statistics.mean),
            "wall_duration_s_median": stat("wall_duration_s", statistics.median),
            "wall_duration_s_stdev": stat("wall_duration_s", statistics.stdev) if n_ok > 1 else (0.0 if n_ok else None),
            "time_to_first_token_s_mean": stat("time_to_first_token_s", statistics.mean),
            "eval_count_mean": eval_count_mean,
            "generation_tokens_per_second": gen_tps,
            "response_word_count_mean": (sum(resp_word_counts) / len(resp_word_counts)) if resp_word_counts else None,
        })
    return summary


# ── CLI ────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", type=str, default=",".join(DEFAULT_MODELS))
    ap.add_argument("--num-predicts", type=str, default=",".join(str(n) for n in DEFAULT_NUM_PREDICTS))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=0)
    ap.add_argument("--level", choices=["a", "b", "both"], default="both")
    ap.add_argument("--timeout", type=float, default=150.0)
    ap.add_argument("--pause-between-blocks", type=float, default=10.0)
    ap.add_argument("--load-avg-threshold", type=float, default=6.0,
                     help="Si load1 > seuil (2 coeurs), pause etendue avant de continuer.")
    ap.add_argument("--test-ids", type=str, default=None)
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",")]
    num_predicts = [int(n) for n in args.num_predicts.split(",")]
    levels = ["a", "b"] if args.level == "both" else [args.level]
    selected_tests = TESTS
    if args.test_ids:
        wanted = {t.strip() for t in args.test_ids.split(",")}
        selected_tests = [t for t in TESTS if t["id"] in wanted]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = RESULTS_DIR / f"raw_{ts}.jsonl"
    meta_path = RESULTS_DIR / f"meta_{ts}.json"
    summary_json_path = RESULTS_DIR / f"summary_{ts}.json"
    summary_csv_path = RESULTS_DIR / f"summary_{ts}.csv"

    print("=== Verification environnement ===")
    ollama_version = check_ollama_running()
    hw = get_hardware_info()
    print(f"Ollama {ollama_version} | CPU {hw['cpu']} ({hw['cpu_count']} coeurs) | "
          f"RAM {hw['ram_total_mb']}MiB (dispo {hw['ram_available_mb']}MiB) | {hw['gpu']}")

    installed = get_installed_models()
    resolved: dict[str, str] = {}
    for m in models:
        actual = resolve_model_name(m, installed)
        if actual is None:
            sys.exit(f"Modele absent : {m} (V2 ne pull aucun modele, cf mission section 2).")
        resolved[m] = actual
        details = get_model_details(actual)
        print(f"  {m} -> {actual} | params={details['parameter_size']} quant={details['quantization_level']}")

    if "b" in levels and not os.getenv("NERON_API_KEY"):
        print("[ATTENTION] NERON_API_KEY absente : le sous-cas num_predict=0 niveau B (service reel) echouera.")

    meta = {
        "timestamp_utc": ts,
        "ollama_version": ollama_version,
        "hardware": hw,
        "models": resolved,
        "num_predicts": num_predicts,
        "runs": args.runs,
        "warmup": args.warmup,
        "levels": levels,
        "timeout_s": args.timeout,
        "test_ids": [t["id"] for t in selected_tests],
        "methodology_note_niveau_b": (
            "num_predict=0 -> appel HTTP direct au service de production reel "
            "(POST /llm/generate, config neron.yaml inchangee). "
            "num_predict in {32,48,64,96,128} -> LLMManager reel instancie dans un "
            "sous-processus isole, pointe via NERON_CONFIG vers une copie temporaire "
            "de neron.yaml ou seul ollama_num_predict differe. Le service de "
            "production (neron@llm.service) n'a jamais ete modifie ni redemarre."
        ),
        "known_gap_found": (
            "server/llm/providers/ollama.py n'envoie jamais 'keep_alive' a Ollama "
            "(verifie par lecture du code) : la valeur llm.keep_alive=10m documentee "
            "dans neron.yaml n'est PAS appliquee par le code actuel. Ollama retombe "
            "sur son propre defaut (5 min). Sans impact sur ce benchmark (calls "
            "rapproches dans le temps) mais pertinent pour l'analyse de latence prod."
        ),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    print(f"\n=== Benchmark V2 : {len(resolved)} modele(s) x {len(num_predicts)} num_predict x "
          f"{len(selected_tests)} tests x ({args.warmup}+{args.runs}) x niveaux={levels} ===")
    print(f"Raw -> {raw_path}\n")

    with open(raw_path, "a") as fh:
        for mi, (requested, actual) in enumerate(resolved.items()):
            print(f"\n--- Modele {mi + 1}/{len(resolved)} : {actual} ---")
            for np_val in num_predicts:
                load1, ram_avail = system_health()
                print(f"  [sante] load1={load1:.2f} ram_dispo={ram_avail}MiB avant num_predict={np_val}")
                if load1 > args.load_avg_threshold:
                    extra = args.pause_between_blocks * 3
                    print(f"  [garde-fou] charge elevee (>{args.load_avg_threshold}) -> pause etendue {extra:.0f}s")
                    time.sleep(extra)

                print(f"  -- num_predict={np_val} --")

                if "a" in levels:
                    for test in selected_tests:
                        for i in range(args.warmup + args.runs):
                            is_warmup = i < args.warmup
                            run_idx = None if is_warmup else i - args.warmup + 1
                            rec = run_ollama_direct(actual, test["prompt"], args.timeout, np_val)
                            rec.update({
                                "num_predict": np_val,
                                "test_id": test["id"],
                                "is_warmup": is_warmup,
                                "run_idx": run_idx,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                            status = "WARMUP" if is_warmup else f"run {run_idx}/{args.runs}"
                            dur = rec.get("wall_duration_s")
                            dur_str = f"{dur:.1f}s" if dur is not None else "?"
                            err_str = f" ERREUR: {rec['error']}" if rec.get("error") else ""
                            print(f"    [A np={np_val}] {test['id']:<22} {status:<10} {dur_str}{err_str}")
                            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                            fh.flush()

                if "b" in levels:
                    if np_val == 0:
                        for test in selected_tests:
                            for i in range(args.warmup + args.runs):
                                is_warmup = i < args.warmup
                                run_idx = None if is_warmup else i - args.warmup + 1
                                rec = run_neron_llm(actual, test["task_type"], test["prompt"], args.timeout)
                                rec.update({
                                    "level": "B_neron_llm_live",
                                    "num_predict": 0,
                                    "test_id": test["id"],
                                    "is_warmup": is_warmup,
                                    "run_idx": run_idx,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                })
                                status = "WARMUP" if is_warmup else f"run {run_idx}/{args.runs}"
                                dur = rec.get("wall_duration_s")
                                dur_str = f"{dur:.1f}s" if dur is not None else "?"
                                err_str = f" ERREUR: {rec['error']}" if rec.get("error") else ""
                                print(f"    [B-live np=0] {test['id']:<22} {status:<10} {dur_str}{err_str}")
                                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                                fh.flush()
                    else:
                        fh.flush()
                        run_inprocess_b(actual, np_val, args.runs, args.warmup, args.timeout, raw_path)

            unload_model(actual)
            if mi < len(resolved) - 1:
                print(f"  (dechargement du modele, pause {args.pause_between_blocks:.0f}s)")
                time.sleep(args.pause_between_blocks)

    print("\n=== Agregation ===")
    summary = aggregate_v2(raw_path)
    summary_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    fieldnames = list(summary[0].keys()) if summary else []
    with open(summary_csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary)

    print(f"Resume JSON -> {summary_json_path}")
    print(f"Resume CSV  -> {summary_csv_path}")
    print(f"Metadonnees -> {meta_path}")

    cleanup_temp_configs()
    print("\nTermine. Configuration de production (neron.yaml, neron@llm.service) jamais modifiee. "
          "Aucun fichier de config temporaire restant.")


if __name__ == "__main__":
    main()
