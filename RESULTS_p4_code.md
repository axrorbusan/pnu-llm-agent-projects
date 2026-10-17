# Project 4 — Detecting API hallucination in LLM-generated code

**One line:** I built a two-layer verifier for LLM-generated Python — AST static analysis against the
real library API, plus sandboxed execution — with a self-repair loop. Across ~290 code samples on
common and even newer/obscure libraries, Claude Haiku 5.5 and Sonnet 5.5 produced **essentially zero
API hallucinations**, so the real risk lies elsewhere (obscure/proprietary libraries, private codebases,
multi-file context) — a concrete research direction.

## The verifier (the contribution)
1. **Static analysis (AST).** Parse the generated code; for every module-level attribute access
   (`np.foo`), `from X import Y`, and keyword argument to a module-level call (`pd.read_csv(bad=...)`),
   check it against the **real installed library** via `importlib` + `hasattr` + `inspect.signature`.
   A reference to a name/argument that does not exist = an API hallucination. (Sound: no false positives;
   the installed library is ground truth.)
2. **Execution.** Run each self-contained script in a sandboxed subprocess (isolated, timeout, temp dir)
   and catch `AttributeError` / `ImportError` / `NameError` — this catches object-method and
   version-drift hallucinations that static analysis alone misses (e.g. `DataFrame.append`, removed in
   pandas 2.0; the installed pandas is 3.0).
3. **Self-repair loop.** On any failure, feed the static error or the runtime traceback back to the model
   and ask it to rewrite using only the real API; re-check. (A linter/runtime-in-the-loop.)

## Results

| layer | samples | API hallucinations | other |
|---|---|---|---|
| static analysis (14 libraries, incl. tricky kwargs) | 160 | 0 | 1 syntax error |
| execution (version-drift-tempting tasks) | 120 | 0 (all ran) | — |
| obscure/newer-API probe (3.12 / pandas 3.0 APIs) | 12 | 0 (all ran) | — |

The models correctly used current APIs even where old ones were removed (`pd.concat`/`.loc` instead of
`DataFrame.append`), and correctly used new APIs (`itertools.batched`, `numpy.trapezoid`,
`Counter.total`, `DataFrame.map`).

## What it shows
- For popular Python libraries, current frontier models essentially do not hallucinate APIs — a clean
  negative result worth knowing, and the opposite of the common assumption.
- Therefore the hallucination risk the field cares about concentrates where the model has **not** seen
  the API: niche or proprietary libraries, internal company codebases, very new releases, and
  cross-file/project context. Those are the interesting cases to study next.
- The verifier itself (static + dynamic + self-repair) is the reusable artifact, and it is exactly a
  static-analysis / program-verification problem.

## Honest caveats
- Tested only popular open-source libraries; that is precisely why the rate is ~0.
- Execution testing was limited to safe, self-contained compute tasks (no network/filesystem).
- Small scale; "~0%" means none observed in ~290 samples, not a guarantee of zero.

Built with an AI coding agent under direction; the verifier design, the choice of version-drift tests,
and the result analysis were reviewed by me.
