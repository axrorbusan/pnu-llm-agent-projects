"""Project 4 — API hallucination in LLM-generated code, caught by static analysis.

The agent is asked to write short Python functions using real standard/third-party libraries.
A static checker (AST-based) extracts module-level attribute accesses (e.g. np.foo, pd.read_csv,
requests.get) and verifies each against the REAL installed library via importlib + hasattr.
A call to a name that does not exist = an API hallucination.

  baseline      : generated code, measure hallucination rate (Haiku vs Sonnet)
  self-verify   : feed the static-analysis errors back, ask the model to fix using only real API,
                  re-measure. (This mirrors a compiler/linter-in-the-loop.)
No LLM judge is needed: the installed libraries are the ground truth.
"""
import ast, json, sys, importlib, re, concurrent.futures as cf
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.agent import call, MODELS, spent_usd

RES = Path(__file__).resolve().parent / "results"; RES.mkdir(parents=True, exist_ok=True)

# Libraries the checker can resolve at module level. All are installed here.
LIBS = ["pandas", "numpy", "requests", "os", "json", "datetime", "collections",
        "re", "itertools", "math", "pathlib", "statistics", "random", "functools"]
ALIAS = {"pd": "pandas", "np": "numpy"}

TASKS = [
 ("pandas", "read a CSV file and return the mean of a numeric column"),
 ("pandas", "drop duplicate rows from a dataframe and reset the index"),
 ("pandas", "group a dataframe by one column and sum another"),
 ("pandas", "merge two dataframes on a shared key column"),
 ("pandas", "convert a column of strings to datetime"),
 ("numpy", "compute the cosine similarity between two 1-D arrays"),
 ("numpy", "return the indices that would sort an array"),
 ("numpy", "compute a moving average of an array with a given window"),
 ("numpy", "generate a 3x3 identity matrix and multiply it by a vector"),
 ("numpy", "clip the values of an array to the range [0, 1]"),
 ("requests", "GET a URL with a 5-second timeout and return the JSON body"),
 ("requests", "POST a JSON payload to a URL and return the status code"),
 ("os", "list all files in a directory that end with .txt"),
 ("os", "create a directory only if it does not already exist"),
 ("json", "read a JSON file and return a specific nested field"),
 ("datetime", "return the number of days between two date strings"),
 ("collections", "count the frequency of items in a list and return the 3 most common"),
 ("re", "extract all email-like substrings from a text"),
 ("itertools", "produce all pairwise combinations of a list"),
 ("math", "compute the great-circle distance between two lat/long points"),
 ("pathlib", "return the file size of a path in bytes"),
 ("statistics", "compute the median and standard deviation of a list of numbers"),
 ("random", "sample 5 unique items from a list without replacement"),
 ("functools", "memoize a recursive function"),
 ("pandas", "pivot a long dataframe to wide format"),
 ("numpy", "solve a linear system Ax=b"),
 ("pandas", "fill missing values in a column with the column mean"),
 ("requests", "download a file in streaming mode and save it to disk"),
 ("collections", "build a dictionary that defaults missing keys to an empty list"),
 ("re", "replace all runs of whitespace in a string with a single space"),
 # trickier tasks that tempt invented keyword arguments or convenience functions
 ("pandas", "read a CSV using only the first 100 rows and only columns A and B, inferring types"),
 ("pandas", "write a dataframe to CSV without the index and with UTF-8 encoding"),
 ("numpy", "load a .npy file using memory mapping in read-only mode"),
 ("requests", "GET a URL following redirects, verifying SSL, with a custom user-agent header"),
 ("pandas", "resample a time-indexed dataframe to daily frequency taking the max"),
 ("json", "serialize an object to a file with 2-space indentation and sorted keys"),
 ("numpy", "stack three arrays depth-wise into one"),
 ("re", "compile a case-insensitive multiline pattern and find all matches"),
 ("datetime", "parse an ISO-8601 timestamp string into a datetime object"),
 ("pandas", "one-hot encode a categorical column, dropping the first level"),
]

CODE_SYS = ("You write short, correct Python. Reply with ONLY a Python code block, no explanation. "
            "Use the real, standard API of the library. Import what you use.")


def gen_code(model, lib, task, fix_note=""):
    prompt = f"Write a Python function that uses the `{lib}` library to {task}.{fix_note}"
    r = call(model, [{"role": "user", "content": prompt}], system=CODE_SYS, max_tokens=1200, tag="p4:gen")
    txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    m = re.search(r"```(?:python)?\s*(.*?)```", txt, re.S)
    return (m.group(1) if m else txt).strip()


_mod_cache = {}
def real_module(name):
    if name not in _mod_cache:
        try: _mod_cache[name] = importlib.import_module(name)
        except Exception: _mod_cache[name] = None
    return _mod_cache[name]


def static_check(code):
    """Return (parse_ok, n_checked, hallucinated).

    Checks three statically-sound things against the REAL installed libraries:
      1. module-level attribute access  (np.foo)           -> must exist on the module
      2. from-import names              (from re import X)  -> must exist on the module
      3. keyword arguments to module-level calls (pd.read_csv(bad=..)) -> must be in the signature
    hallucinated entries are strings like "numpy.foo" or "pandas.read_csv(bad_kwarg)".
    """
    import inspect
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False, 0, []
    imported = {}
    checked, halluc = 0, []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported[a.asname or a.name.split(".")[0]] = a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and node.module in LIBS:
            mod = real_module(node.module)
            if mod is not None:
                for a in node.names:
                    if a.name == "*":
                        continue
                    checked += 1
                    if not hasattr(mod, a.name):
                        halluc.append(f"from {node.module} import {a.name}")
    for node in ast.walk(tree):
        # module-level attribute access
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            base = node.value.id
            modname = imported.get(base) or ALIAS.get(base)
            if modname and modname in LIBS:
                mod = real_module(modname)
                if mod is not None:
                    checked += 1
                    if not hasattr(mod, node.attr):
                        halluc.append(f"{modname}.{node.attr}")
        # keyword arguments to a module-level call: mod.func(kw=...)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) and node.keywords:
            base = node.func.value.id
            modname = imported.get(base) or ALIAS.get(base)
            mod = real_module(modname) if modname in LIBS else None
            fn = getattr(mod, node.func.attr, None) if mod else None
            if fn is not None and callable(fn):
                try:
                    sig = inspect.signature(fn)
                    params = sig.parameters
                    has_var_kw = any(p.kind == p.VAR_KEYWORD for p in params.values())
                    if not has_var_kw:
                        for kw in node.keywords:
                            if kw.arg is None:
                                continue
                            checked += 1
                            if kw.arg not in params:
                                halluc.append(f"{modname}.{node.func.attr}({kw.arg}=)")
                except (ValueError, TypeError):
                    pass  # some builtins have no introspectable signature
    return True, checked, halluc


def process(model_key, lib, task):
    model = MODELS[model_key]
    base = gen_code(model, lib, task)
    ok, n_checked, hall = static_check(base)
    rec = {"model": model_key, "lib": lib, "task": task, "base_code": base,
           "base_parse_ok": ok, "base_calls": n_checked, "base_halluc": hall}
    # self-verification only if there was a problem
    if hall or not ok:
        note = ""
        if not ok:
            note = " Your previous code had a syntax error; return corrected, parseable code."
        if hall:
            names = ", ".join(f"{m}.{a}" for m, a in hall)
            note = (f" A static check found these do NOT exist in the real library: {names}. "
                    "Rewrite using only real API.")
        rev = gen_code(model, lib, task, fix_note=note)
        ok2, n2, hall2 = static_check(rev)
        rec.update(rev_code=rev, rev_parse_ok=ok2, rev_calls=n2, rev_halluc=hall2, revised=True)
    else:
        rec.update(revised=False, rev_halluc=[], rev_parse_ok=ok, rev_calls=n_checked)
    return rec


def main(models=("haiku", "sonnet"), repeats=2):
    jobs = [(m, lib, task) for m in models for (lib, task) in TASKS for _ in range(repeats)]
    print(f"{len(jobs)} code-gen runs; spent ${spent_usd():.3f}", flush=True)
    out = RES / "raw.jsonl"; done = 0
    with out.open("w") as f, cf.ThreadPoolExecutor(max_workers=6) as ex:
        for rec in ex.map(lambda j: process(*j), jobs):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); done += 1
            if done % 20 == 0: print(f"{done}/{len(jobs)}; spent ${spent_usd():.3f}", flush=True)
    print(f"done; spent ${spent_usd():.3f}")


if __name__ == "__main__":
    main()
