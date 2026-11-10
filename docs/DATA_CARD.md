# Data Card

GigBid's world is a mix of **real** job-market data (Kaggle) and **synthetic** data where no real data exists.
Every generated record says which it is. Regenerate everything with `make data`.

## 1. Sources (real)

| Dataset | Author / link | License | Used for |
|---|---|---|---|
| Upwork freelance jobs (+60k), Feb-Mar 2023 | ahmedmyalo, kaggle.com/datasets/ahmedmyalo/upwork-freelance-jobs-60k | Apache-2.0 | GigSim live job pool, historical jobs, client attributes, Connects cost, skill vocabulary |
| Upwork Job Postings Dataset 2024 (50K) | asaniczka, kaggle.com/datasets/asaniczka/upwork-job-postings-dataset-2024-50k-records | ODC-By 1.0 | Price statistics (fixed budgets, hourly ranges); past-proposal job contexts |

Not used (evaluated and rejected): `all-jobs-on-upwork-200k-plus` (overlaps the 2024 set), `freelance-contracts-dataset-1-3-million-entries` (job title + paid amounts only, no descriptions; possible later use for rate statistics), `freelancer-success-earnings-and-churn-prediction` and `trial-1` (freelancer-level aggregates, no jobs).

Attribution: job text is reproduced from the datasets above under their licenses. Both datasets were originally collected from public Upwork listings by their authors; GigBid itself never scrapes Upwork.

## 2. Preprocessing (`scripts/data/preprocess.py`)
1. Text cleaning: replace scrape mojibake (`U+FFFD` -> `'`), collapse whitespace.
2. Normalise to one schema: title, description, skills (60k: `Category_1..9`; 2024: extracted by matching the 60k skill vocabulary, tags seen >= 40 times), payment type, budget / hourly range, experience level, duration, Connects cost (`New_Connects_Num`), client attributes.
3. Category assignment (`ai_ml`, `web_dev`, `data_analysis`, `other`) by keyword rules over title + description + skills (>= 2 distinct keyword hits; 60k falls back to its search keyword).
4. Drop descriptions under 120 chars; deduplicate on normalised title + first 300 chars of description (6,375 removed). 103,405 unique jobs remain.
5. Market price quantiles per category and category x experience level -> `data/gigsim_seed/market_stats.json`.

## 3. Synthetic data (`scripts/data/generate_synthetic.py`, `scripts/data/persona_catalog.py`, seed 42)

| Artifact | Real or synthetic | How it is made |
|---|---|---|
| Three personas (AI/ML engineer, full-stack developer, data analyst) | **Synthetic** | Hand-written catalog: 15 projects each with client, industry, year, named skills, *implied* skills (only in code), problem, approach, result |
| Case studies, CV, repo READMEs + code, reviews | **Synthetic** | Generated from the catalog. The same project is described several ways; READMEs are deliberately vague; implied skills appear only in code imports |
| Past proposals (150 per persona) with outcome won / replied / ignored | **Synthetic text on real jobs** | Each proposal answers a real job; text is templated (generic vs specific opening); outcome sampled from a model where specificity and skill overlap raise reply odds |
| GigSim job pool (997) | **Mostly real** | 690 real in-category jobs (230 per persona) + 150 real off-category jobs, plus 72 synthetic scams, 45 prompt-injection jobs (real job + planted instruction) and 40 duplicate reposts (real job, cosmetic edits) |
| Historical jobs (1,500) | **Real** + synthetic award amount | Closed jobs for client history; `awarded_amount` = budget x U(0.8, 1.05) |
| Client profiles | **Real attributes**, synthetic ids | The 60k data has no client id: jobs sharing country + total spent + rating + review count + payment-verified are treated as one pseudo-client |
| Client hidden preferences | **Synthetic** | must-have skills (sampled from the client's job skills), budget ceiling factor U(1.0, 1.35), dislikes generic openings (p = 0.65), reply propensity U(0.3, 0.9) |
| Gold labels (dev / holdout) | **Rule-derived** | See section 4 |

Provenance of every pool job is in `data/gigsim_seed/provenance.jsonl` (not served by the GigSim API, so agents cannot use it to cheat).

## 4. Gold labels (`evals/datasets/{dev,holdout}/labels.jsonl`)
One row per (job, persona). 997 jobs x 3 personas; split by job: dev 736 jobs (2,208 rows), holdout 261 jobs (783 rows). The holdout is never used for tuning. The instructor's hidden test set is separate and never enters the repo.

- `is_scam`, `scam_type`, `has_injection`, `injection_type`, `duplicate_of`: known by construction.
- `fit_score`: share of job requirements (tags + persona skills named in the text, canonicalised with a synonym map, generic tags like "English" removed) covered by the persona's skills + project skills.
- `gold_evidence_projects`: up to 5 projects whose skills (named + implied) overlap the requirements in >= 2 skills.
- `bid`: true only if not a scam, no injection, not a duplicate, fit >= 0.4, at least one gold project, and the price is acceptable (fixed budget >= persona minimum, or hourly max >= 60% of persona rate). `skip_reasons` lists every failing condition.
- `fair_price`: fixed: [max(min, 0.75 x budget), max(min, budget)], or category p25-p75 if no budget; hourly: [max(0.85 x rate, client low), max(1.15 x rate, client high)].

## 5. Limitations
- **Labels are rule-derived, not human-judged.** They inherit the keyword categoriser's errors (for example, some game-development posts land in `data_analysis`). A hand audit of a sample is reported with the evaluation.
- Pseudo-clients can merge different real clients with identical attributes, or split one real client.
- Job data is from Feb-Mar 2023 (pool) and Feb 2024 (pricing): prices and skill demand (e.g. LLM work) have shifted since.
- Scam and injection posts are template-based, so they are less varied than real ones; detection rates on them are optimistic.
- Simulated client behaviour is a simple, documented scoring model (`gigsim/client_sim.py`), not real human behaviour. Reply rates measure "does the proposal hit what this simulator rewards", which was designed to reflect common client complaints (generic openings, no evidence, over budget).
- Synthetic portfolios are cleaner than real ones (consistent dates, no typos).

## 6. Handling
- Raw Kaggle files live in `data/raw/` (git-ignored); `data/processed/` is git-ignored and regenerated.
- Committed: generated seed (`data/gigsim_seed/`), personas (`data/personas/`) and labels, so results reproduce without Kaggle access.
- No personal data: real job posts may contain names or contact details written by clients; GigBid masks emails and phone numbers in logs and traces.
