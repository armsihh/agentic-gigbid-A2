"""Clean and merge the two Kaggle Upwork datasets into one normalised job table.

Inputs (git-ignored, download manually, see docs/DATA_CARD.md):
  data/raw/kaggle/Upwork Freelance Jobs/Final_Upwork_Dataset.csv      (ahmedmyalo, Apache-2.0)
  data/raw/kaggle/Upwork Job Postings Dataset 2024/upwork-jobs.csv    (asaniczka, ODC-By)

Outputs:
  data/processed/jobs_real.parquet     every cleaned real job (git-ignored, large)
  data/gigsim_seed/market_stats.json   price quantiles per category / level (committed, small)

Run:  uv run python -m scripts.data.preprocess
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "kaggle"
SRC_60K = RAW / "Upwork Freelance Jobs" / "Final_Upwork_Dataset.csv"
SRC_50K = RAW / "Upwork Job Postings Dataset 2024" / "upwork-jobs.csv"
OUT_PROCESSED = ROOT / "data" / "processed"
OUT_SEED = ROOT / "data" / "gigsim_seed"

# Keyword rules that map a job to one of the persona categories. Order matters only on ties.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "ai_ml": [
        "machine learning", "deep learning", "artificial intelligence", "neural network", "nlp",
        "natural language processing", "computer vision", "pytorch", "tensorflow", "keras",
        "llm", "langchain", "openai", "chatgpt", "gpt", "rag", "hugging face", "transformers",
        "scikit-learn", "model training", "fine-tun", "chatbot", "data science", "ai model",
    ],
    "web_dev": [
        "react", "next.js", "nextjs", "node.js", "nodejs", "express", "django", "flask",
        "fastapi", "full stack", "full-stack", "fullstack", "web application", "web app",
        "frontend", "front-end", "backend", "back-end", "typescript", "javascript", "vue",
        "angular", "rest api", "graphql", "postgresql", "mongodb", "tailwind", "laravel", "php",
    ],
    "data_analysis": [
        "data analysis", "data analyst", "power bi", "tableau", "looker", "dashboard", "excel",
        "google sheets", "sql", "data visualization", "statistic", "reporting", "etl", "dbt",
        "bigquery", "data cleaning", "pivot", "kpi", "a/b test",
    ],
}

SEARCH_KEYWORD_TO_CATEGORY = {"Developer": "web_dev", "Data_science": "data_analysis"}


def clean_text(s: object) -> str:
    if not isinstance(s, str):
        return ""
    s = s.replace("�", "'")  # mojibake from the scrape (smart quotes lost)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def money(s: object) -> float | None:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", str(s))
    if not m:
        return None
    v = float(m.group(0).replace(",", ""))
    return v if v > 0 else None


def stable_id(prefix: str, *parts: object) -> str:
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]
    return f"{prefix}-{h}"


_CAT_RE = {
    cat: re.compile(r"(?<![a-z])(" + "|".join(re.escape(k) for k in kws) + ")")
    for cat, kws in CATEGORY_KEYWORDS.items()
}


def categorise(text: str, skills: list[str], fallback: str | None = None) -> str:
    blob = (text + " " + " ".join(skills)).lower()
    # count distinct keywords hit per category (one alternation regex per category = fast)
    scores = {cat: len(set(rx.findall(blob))) for cat, rx in _CAT_RE.items()}
    best, score = max(scores.items(), key=lambda kv: kv[1])
    if score >= 2:
        return best
    return fallback or "other"


def load_60k() -> pd.DataFrame:
    df = pd.read_csv(SRC_60K, low_memory=False)
    skill_cols = [f"Category_{i}" for i in range(1, 10)]
    out = pd.DataFrame()
    out["title"] = df["Job Title"].map(clean_text)
    out["description"] = df["Description"].map(clean_text)
    out["skills"] = df[skill_cols].apply(
        lambda r: [clean_text(x) for x in r if isinstance(x, str) and x.strip()], axis=1
    )
    out["experience_level"] = df["EX_level_demand"].fillna("Unspecified")
    out["duration"] = df["Time_Limitation"].fillna("")
    out["payment_type"] = df["Payment_type"].map(
        lambda x: "hourly" if str(x).lower().startswith("hourly") else "fixed"
    )
    out["budget"] = df["Job_Cost"].map(money)
    out["hourly_low"] = df["Start_rate"].map(money)
    out["hourly_high"] = df["End_rate"].map(money)
    out.loc[out["payment_type"] == "fixed", ["hourly_low", "hourly_high"]] = None
    out["connects_cost"] = df["New_Connects_Num"].fillna(8).astype(int)
    out["applicants"] = df["Applicants_Num"].fillna("Unknown")
    out["freelancers_needed"] = df["Freelancers_Num"]
    out["country"] = df["Client_Country"].fillna("Unknown")
    out["client_payment_verified"] = df["Payment_Situation"].eq("Payment verified")
    out["client_total_spent"] = df["Spent($)"].fillna(0.0)
    out["client_rating"] = df["Rating"]
    out["client_reviews"] = df["Feedback_Num"].fillna(0).astype(int)
    out["client_enterprise"] = df["Enterprise_Client"].notna()
    out["search_keyword"] = df["Search_Keyword"].fillna("")
    out["source"] = "kaggle:ahmedmyalo/upwork-freelance-jobs-60k"
    out["source_year"] = 2023
    # The dataset has no client id; jobs that share every client attribute are treated as
    # one pseudo-client. Documented as a limitation in DATA_CARD.md.
    out["client_id"] = [
        stable_id("cl", c, s, r, n, v)
        for c, s, r, n, v in zip(
            out["country"], out["client_total_spent"], out["client_rating"],
            out["client_reviews"], out["client_payment_verified"],
        )
    ]
    out["category"] = [
        categorise(t + " " + d, s, SEARCH_KEYWORD_TO_CATEGORY.get(k))
        for t, d, s, k in zip(out["title"], out["description"], out["skills"], out["search_keyword"])
    ]
    return out


def load_50k(vocab: list[str]) -> pd.DataFrame:
    df = pd.read_csv(SRC_50K)
    out = pd.DataFrame()
    out["title"] = df["title"].map(clean_text)
    out["description"] = df["description"].map(clean_text)
    # one combined alternation (longest first) instead of 400 separate regexes
    canon = {v.lower(): v for v in vocab}
    alt = "|".join(re.escape(v) for v in sorted(canon, key=len, reverse=True))
    rx = re.compile(r"(?<![a-z])(" + alt + r")(?![a-z])")

    def extract(text: str) -> list[str]:
        found = dict.fromkeys(canon[m] for m in rx.findall(text.lower()))
        return list(found)[:9]

    out["skills"] = [extract(t + " " + d) for t, d in zip(out["title"], out["description"])]
    hourly = df["is_hourly"].astype(str).str.lower().eq("true")
    out["payment_type"] = np.where(hourly, "hourly", "fixed")
    out["budget"] = df["budget"].where(~hourly)
    out["hourly_low"] = df["hourly_low"].where(hourly)
    out["hourly_high"] = df["hourly_high"].where(hourly)
    out["experience_level"] = "Unspecified"
    out["duration"] = ""
    out["country"] = df["country"].fillna("Unknown")
    out["published_date"] = df["published_date"]
    out["source"] = "kaggle:asaniczka/upwork-job-postings-dataset-2024-50k-records"
    out["source_year"] = 2024
    out["category"] = [categorise(t + " " + d, s) for t, d, s in zip(out["title"], out["description"], out["skills"])]
    return out


def market_stats(df: pd.DataFrame) -> dict:
    def q(series: pd.Series) -> dict | None:
        s = series.dropna()
        s = s[(s > 0) & (s < s.quantile(0.99))] if len(s) > 50 else s[s > 0]
        if len(s) < 10:
            return None
        return {
            "n": len(s),
            **{f"p{p}": round(float(s.quantile(p / 100)), 2) for p in (10, 25, 50, 75, 90)},
        }

    stats: dict = {"by_category": {}, "by_category_level": {}}
    for cat, g in df.groupby("category"):
        stats["by_category"][cat] = {"fixed_budget": q(g["budget"]), "hourly_high": q(g["hourly_high"]),
                                     "hourly_low": q(g["hourly_low"])}
        for lvl, gg in g.groupby("experience_level"):
            stats["by_category_level"][f"{cat}|{lvl}"] = {
                "fixed_budget": q(gg["budget"]), "hourly_high": q(gg["hourly_high"]),
            }
    return stats


def main() -> None:
    OUT_PROCESSED.mkdir(parents=True, exist_ok=True)
    OUT_SEED.mkdir(parents=True, exist_ok=True)

    a = load_60k()
    counts = Counter(s for skills in a["skills"] for s in skills)
    vocab = [s for s, n in counts.most_common() if n >= 40 and len(s) > 1]
    b = load_50k(vocab)

    df = pd.concat([a, b], ignore_index=True)
    df = df[df["description"].str.len() >= 120]
    df["dedup_key"] = (df["title"].str.lower().str.replace(r"\W+", "", regex=True) + "|"
                       + df["description"].str.lower().str.replace(r"\W+", "", regex=True).str[:300])
    before = len(df)
    df = df.drop_duplicates("dedup_key").drop(columns="dedup_key")
    df["job_id"] = [stable_id("job", t, d[:200]) for t, d in zip(df["title"], df["description"])]
    df = df.drop_duplicates("job_id").reset_index(drop=True)

    df.to_parquet(OUT_PROCESSED / "jobs_real.parquet", index=False)
    stats = market_stats(df)
    stats["skill_vocab"] = vocab[:400]
    (OUT_SEED / "market_stats.json").write_text(json.dumps(stats, indent=2))

    print(f"60k rows: {len(a)}  50k rows: {len(b)}  after clean+dedup: {len(df)} (dropped {before - len(df)} dups)")
    print(df["category"].value_counts().to_string())
    print(df.groupby(["source_year", "payment_type"]).size().to_string())


if __name__ == "__main__":
    main()
