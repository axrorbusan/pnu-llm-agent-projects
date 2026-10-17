# Project 2 — Monitoring an LLM agent's tool calls

**One line:** A careful agent rarely leaks marked secrets on its own, so the monitoring layer is
tested against compromised sessions; there, a simple interpretable policy rule catches 100% of
compromised sessions with no false positives, while an unsupervised Isolation Forest on coarse
behavioral features catches almost none — because these are policy violations, not statistical outliers.

## Setup
- The same agent runs 168 normal sessions (7 task types, 2 models, varied inputs). Its workspace holds
  project files containing synthetic **canary tokens** marked "confidential."
- Every tool call is logged (time, tool, arguments, output size).

## Part A — leak detection on outgoing messages
- Natural leakage: **0 / 168** sessions copied a confidential token into an outgoing message — the models
  respect the "confidential" marking.
- Detectors evaluated on 120 real clean messages + 60 simulated compromised messages (a compromised agent
  appends a token):

| detector | precision | recall | F1 |
|---|---|---|---|
| keyword-proximity rule | 0.55 | 0.82 | 0.66 |
| canary-token pattern rule | 1.00 | 1.00 | 1.00 |

The pattern rule is perfect **for planted canaries** (known format); real unknown secrets would need the
noisier keyword rule or content inspection — an honest limitation.

## Part B — behavior anomaly detection on tool-call logs
- Normal = 168 real sessions; abnormal = 40 scripted compromised sequences (credential read + send,
  redirect to unknown recipient, send burst, oversized exfil).

| detector | precision | recall | F1 |
|---|---|---|---|
| interpretable policy rule | 1.00 | 1.00 | 1.00 |
| Isolation Forest (coarse features) | — | 0.00 | 0.00 |

Loosening the Isolation Forest threshold until it wrongly flags 19/51 normal sessions **still** catches
0/40 compromised ones: the compromised sessions' anomaly scores overlap the normal range.

## What it shows
- The real signals of a compromised agent (unapproved recipient, reading a credential file, send bursts)
  are **categorical policy violations**, not statistical outliers, so an explicit rule layer beats naive
  unsupervised anomaly detection when normal behavior is low-variance.
- Effective ML-based anomaly detection here would need richer features or labeled incidents — a concrete
  next research step.

## Honest caveats
- Compromised sessions are scripted, not adversarially generated.
- Canary detection benefits from a known token format.
