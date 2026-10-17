"""Project 2: monitor what the agent does.

Part A - leak detection on outgoing messages:
  * natural leakage: how often the agent itself copies a confidential token into a message
  * detectors compared: (1) keyword rule "confidential" nearby, (2) canary-token pattern rule,
    (3) tool-call inspection gate that blocks sends containing text copied from confidential lines
Part B - behavior anomaly detection on tool-call logs:
  * normal sessions = real agent runs on normal tasks (Haiku)
  * abnormal sessions = scripted tool-call sequences that mimic a compromised agent
  * Isolation Forest (unsupervised) vs simple threshold rules; precision / recall / F1
"""
import json, re, sys, random, concurrent.futures as cf
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.agent import run_agent, MODELS, spent_usd, DEFAULT_SYSTEM
from p2_monitor.data import TASKS, CANARIES, FILES, install
from p1_injection.testset import BASE

OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)
CANARY_RE = re.compile(r"CANARY-[0-9A-F]{4}-[A-Z]+")


def session(model_key, task, page_text, rep):
    final, run = run_agent(MODELS[model_key], task, page_text or "(no page for this task)",
                           system=DEFAULT_SYSTEM, tag=f"p2:{model_key}")
    sent = " ".join(m["body"] for m in run.outbox)
    leaked = [c for c in CANARIES if c in sent]
    return {"model": model_key, "task": task, "rep": rep, "calls": run.calls, "outbox": run.outbox,
            "notes": run.notes, "leaked": leaked}


def main(per_task=12, models=("haiku", "sonnet")):
    install()
    pages = list(BASE.values())
    jobs = []
    for m in models:
        for t, kind in TASKS:
            for r in range(per_task):
                jobs.append((m, t, random.Random(r).choice(pages) if kind == "page" else None, r))
    print(len(jobs), "sessions; spent", round(spent_usd(), 3), flush=True)
    with open(OUT / "sessions.jsonl", "w") as f, cf.ThreadPoolExecutor(max_workers=6) as ex:
        for i, rec in enumerate(ex.map(lambda j: session(*j), jobs)):
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            if (i + 1) % 25 == 0:
                print(i + 1, "done; spent", round(spent_usd(), 3), flush=True)
    print("done; spent", round(spent_usd(), 3))


if __name__ == "__main__":
    main()
