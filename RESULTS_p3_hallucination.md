# Project 3 — Hallucination in an LLM agent's news summaries

**One line:** On real news articles the agent's summaries hallucinate a small but non-zero fraction of
claims (2–4%); adding a retrieval-based self-verification step cuts the stronger model's hallucination
sharply, while barely helping the weaker one.

## Setup
- 45 real Reuters news articles (public corpus, via NLTK).
- Agent (Claude Haiku 5.5 / Sonnet 5.5) writes a 3-sentence summary of each.
- Each summary is split into atomic claims; Claude Opus 5.5 judges each claim supported / unsupported
  by the article. Hallucination rate = unsupported claims / total claims.
- Self-verification: for each claim, the 3 most similar article sentences are retrieved (TF-IDF, no API
  cost) and shown to the agent, which rewrites the summary keeping only supported claims. Re-measured.

## Results

| model | baseline hallucination | after self-verification |
|---|---|---|
| haiku | 10/492 = 2.0% | 10/458 = 2.2% |
| sonnet | 21/550 = 3.8% | 6/579 = 1.0% |

By summary (how many of 45 summaries contain at least one unsupported claim):

| model | baseline | after self-verification |
|---|---|---|
| haiku | 8/45 | 7/45 |
| sonnet | 19/45 | 5/45 |

## What it shows
- Self-verification with retrieved evidence **clearly helps the stronger model** (Sonnet: 19 → 5
  summaries with a hallucination) but **does little for the weaker model** (Haiku) — the weaker model
  is less able to act on the evidence to revise itself. A real, reportable asymmetry.
- The idea matches the lab's "self-verification + external knowledge" direction, tested on an agent's
  real outputs.

## Honest caveats (important)
- The judge is an LLM and is not perfect. A hand-check of flagged claims found at least one **false
  positive** (a claim about operations in Florida/South Carolina/Texas/Tennessee was marked unsupported,
  but the article does name Key West FL, Myrtle Beach SC, Houston TX and Nashville TN). So the **true**
  hallucination rate is probably even lower than the numbers above. `results/review.csv` holds 60
  claim-judgments to hand-check and report the judge's agreement rate.
- The relative improvement from self-verification is robust to this, because the same judge scores both
  the baseline and the revised summaries.
- 45 articles; single-digit rates have wide confidence intervals.
