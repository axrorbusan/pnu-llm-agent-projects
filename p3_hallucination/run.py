"""Project 3: measure and reduce hallucination in the agent's news summaries.

Pipeline per article:
  1. agent summarizes the article (Haiku / Sonnet)
  2. extract atomic factual claims from the summary (Haiku)
  3. judge each claim as supported / unsupported by the article (Opus, all claims of a summary in one call)
  -> baseline hallucination rate = unsupported claims / total claims
  4. self-verification: for each claim, retrieve the 3 most similar article sentences (TF-IDF, free),
     show them to the agent, and have it rewrite the summary keeping only supported claims
  -> re-measure hallucination rate on the revised summary
A sample of claim judgments is written to review.csv for the user to hand-check.
"""
import json, sys, re, concurrent.futures as cf
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.agent import call, MODELS, spent_usd

HERE = Path(__file__).resolve().parent
ART = json.load(open(HERE / "articles.json"))
RES = HERE / "results"; RES.mkdir(exist_ok=True)


def summarize(model, article, extra=""):
    msg = [{"role": "user", "content":
            f"Summarize the following news article in 3 sentences for a busy reader.{extra}\n\nArticle:\n{article}"}]
    r = call(model, msg, max_tokens=1200, tag="p3:sum")
    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()


def extract_claims(summary):
    msg = [{"role": "user", "content":
            "Break the text into a numbered list of short, standalone factual claims (one fact each). "
            "Output only the list.\n\nText:\n" + summary}]
    r = call(MODELS["haiku"], msg, max_tokens=1200, tag="p3:claims")
    txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    claims = [re.sub(r"^\s*\d+[\.\)]\s*", "", ln).strip() for ln in txt.splitlines() if ln.strip()]
    return [c for c in claims if len(c) > 8]


def judge_claims(article, claims):
    numbered = "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims))
    msg = [{"role": "user", "content":
            "You check whether each claim is supported by the article. A claim is 'supported' only if the article "
            "states or clearly implies it. Otherwise 'unsupported'.\n\n"
            f"ARTICLE:\n{article}\n\nCLAIMS:\n{numbered}\n\n"
            'Answer JSON only: {"verdicts": ["supported"|"unsupported", ...]} in claim order.'}]
    r = call(MODELS["opus"], msg, max_tokens=1200, tag="p3:judge")
    txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    try:
        s = txt[txt.index("{"): txt.rindex("}") + 1]
        v = json.loads(s)["verdicts"]
        return (v + ["unsupported"] * len(claims))[:len(claims)]
    except Exception:
        return ["parse_error"] * len(claims)


def sentences(article):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", article) if len(s.strip()) > 15]


def retrieve(claim, sents, k=3):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    vec = TfidfVectorizer().fit(sents + [claim])
    S = vec.transform(sents); q = vec.transform([claim])
    sims = cosine_similarity(q, S)[0]
    idx = sims.argsort()[::-1][:k]
    return [sents[i] for i in idx]


def self_verify(model, article, summary, claims):
    sents = sentences(article)
    evidence = {c: retrieve(c, sents) for c in claims}
    ev_text = "\n".join(f"- Claim: {c}\n  Evidence from article: {' | '.join(evidence[c])}" for c in claims)
    msg = [{"role": "user", "content":
            "Here is a draft summary and, for each claim in it, the most relevant sentences from the source article. "
            "Rewrite the summary in 3 sentences, keeping ONLY claims that the evidence supports and dropping or "
            "correcting anything not supported.\n\n"
            f"ARTICLE:\n{article}\n\nDRAFT SUMMARY:\n{summary}\n\nCLAIMS AND EVIDENCE:\n{ev_text}"}]
    r = call(model, msg, max_tokens=1200, tag="p3:verify")
    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()


def process(model_key, art):
    model = MODELS[model_key]
    base = summarize(model, art["text"])
    bc = extract_claims(base)
    bv = judge_claims(art["text"], bc) if bc else []
    # self-verification pass
    rev = self_verify(model, art["text"], base, bc) if bc else base
    rc = extract_claims(rev)
    rv = judge_claims(art["text"], rc) if rc else []
    return {"id": art["id"], "model": model_key,
            "base_summary": base, "base_claims": bc, "base_verdicts": bv,
            "rev_summary": rev, "rev_claims": rc, "rev_verdicts": rv}


def main(models=("haiku", "sonnet"), n=45):
    arts = ART[:n]
    jobs = [(m, a) for m in models for a in arts]
    print(f"{len(jobs)} article-runs; spent ${spent_usd():.3f}", flush=True)
    out = RES / "raw.jsonl"
    done = 0
    with out.open("w") as f, cf.ThreadPoolExecutor(max_workers=5) as ex:
        for rec in ex.map(lambda j: process(*j), jobs):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); done += 1
            if done % 10 == 0:
                print(f"{done}/{len(jobs)} done; spent ${spent_usd():.3f}", flush=True)
    print(f"done; spent ${spent_usd():.3f}")


if __name__ == "__main__":
    main()
