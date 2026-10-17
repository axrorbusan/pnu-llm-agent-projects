"""Project 4, execution-based part: version-drift API hallucination + self-repair.

The agent writes a SELF-CONTAINED Python script for a task. The script is run in a sandboxed
subprocess (timeout, no network needed, temp dir). We record whether it runs or raises an
API error (AttributeError / TypeError / ImportError / NameError) — i.e. it called an API that
does not exist in the installed library version. Then a self-repair loop feeds the traceback
back to the model and re-runs. This is a linter/runtime-in-the-loop over LLM-generated code.

Tasks are chosen to touch APIs that changed across library versions (pandas 3.0, numpy 2.4 here),
a common real cause of LLM code hallucination.
"""
import json, sys, re, subprocess, tempfile, os, concurrent.futures as cf
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.agent import call, MODELS, spent_usd

RES = Path(__file__).resolve().parent / "results"; RES.mkdir(parents=True, exist_ok=True)

# Self-contained tasks; several deliberately touch version-sensitive APIs.
TASKS = [
 "create a pandas DataFrame with columns a,b and two rows, append a new row {a:5,b:6}, and print the result",
 "create a pandas DataFrame and add a new row to it from a dictionary, then print it",
 "make a numpy array of Python ints and cast it to a numpy integer dtype, then print its dtype",
 "create a numpy array and check whether all its elements are nonzero, print True/False",
 "build a pandas Series and print its most frequent value",
 "create a DataFrame with a date column and set it as a datetime index, then resample to monthly sums and print",
 "concatenate two small pandas DataFrames vertically and print the result",
 "create a DataFrame, group by a column, and get the mean of another column, then print",
 "make a numpy 2x2 matrix and print its inverse",
 "create a pandas DataFrame with a NaN and fill missing values with 0, then print",
 "one-hot encode a small categorical pandas Series and print the result",
 "create a numpy array of floats and print the element-wise natural log",
 "build a pandas DataFrame and iterate over its rows printing each row's values",
 "create a DataFrame and apply a function to one column to make a new column, then print",
 "make a numpy array and print its cumulative sum",
 "create a pandas DataFrame and sort it by a column in descending order, then print",
 "build a dict-like counter of words in a sentence and print the two most common",
 "create a numpy array and reshape it from shape (6,) to (2,3), then print",
 "parse the ISO timestamp '2026-01-02T03:04:05' into a datetime and print the year",
 "create a pandas DataFrame and drop a column by name, then print",
]

SYS = ("You write a short, COMPLETE, runnable Python script (not just a function). "
       "Reply with ONLY a Python code block. The script must run top to bottom and print a result. "
       "Use the real, current API of the libraries installed.")

API_ERRORS = ("AttributeError", "ImportError", "ModuleNotFoundError", "NameError")


def gen(model, task, fix=""):
    r = call(model, [{"role": "user", "content": f"Task: {task}.{fix}"}], system=SYS, max_tokens=1200, tag="p4x:gen")
    txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    m = re.search(r"```(?:python)?\s*(.*?)```", txt, re.S)
    return (m.group(1) if m else txt).strip()


def run_script(code, timeout=15):
    """Run code in a sandboxed subprocess. Return (ok, error_type, tail)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.py"
        p.write_text(code)
        try:
            r = subprocess.run([sys.executable, "-I", str(p)], cwd=d, capture_output=True,
                               text=True, timeout=timeout,
                               env={**os.environ, "MPLBACKEND": "Agg"})
        except subprocess.TimeoutExpired:
            return False, "Timeout", "timed out"
        if r.returncode == 0:
            return True, "", r.stdout[-300:]
        err = r.stderr.strip()
        etype = "OtherError"
        last = [ln for ln in err.splitlines() if ":" in ln and "Error" in ln]
        if last:
            etype = last[-1].split(":")[0].split(".")[-1].strip()
        return False, etype, err[-400:]


def process(model_key, task):
    model = MODELS[model_key]
    code = gen(model, task)
    ok, etype, tail = run_script(code)
    rec = {"model": model_key, "task": task, "base_code": code, "base_ok": ok,
           "base_error": etype, "base_api_hallucination": (not ok and etype in API_ERRORS)}
    if not ok:
        fix = (f" Your previous script failed with this error, which means it used an API that does not "
               f"exist in the installed version:\n{tail}\nRewrite it using only the current, real API.")
        code2 = gen(model, task, fix=fix)
        ok2, etype2, tail2 = run_script(code2)
        rec.update(revised=True, rev_code=code2, rev_ok=ok2, rev_error=etype2,
                   rev_api_hallucination=(not ok2 and etype2 in API_ERRORS))
    else:
        rec.update(revised=False, rev_ok=True, rev_error="", rev_api_hallucination=False)
    return rec


def main(models=("haiku", "sonnet"), repeats=3):
    jobs = [(m, t) for m in models for t in TASKS for _ in range(repeats)]
    print(f"{len(jobs)} runs; spent ${spent_usd():.3f}", flush=True)
    out = RES / "exec_raw.jsonl"; done = 0
    with out.open("w") as f, cf.ThreadPoolExecutor(max_workers=5) as ex:
        for rec in ex.map(lambda j: process(*j), jobs):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); done += 1
            if done % 15 == 0: print(f"{done}/{len(jobs)}; spent ${spent_usd():.3f}", flush=True)
    print(f"done; spent ${spent_usd():.3f}")


if __name__ == "__main__":
    main()
