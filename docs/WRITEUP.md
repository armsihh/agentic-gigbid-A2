# My agent scored 0.92. Then I looked at the data it had never seen.

*What building a multi-agent freelancing copilot taught me about measuring it. Numbers are from my own result files.*

For a university assignment I built GigBid: a team of LangGraph agents that reads freelance job posts, flags scams,
decides whether a job is worth paying to bid on, writes a proposal where every claim is backed by the freelancer's
real portfolio, and waits for a human to approve anything before it is sent. It runs against a marketplace simulator I
built from about 100,000 real Upwork job posts, three synthetic freelancers with portfolios, and planted scams and
prompt-injection posts.

I expected the hard parts to be the agents: the parallel graph, the critic loop, the approval step that survives a
server crash. Those took effort, but they did what they were designed to do. The surprising part was how easily my
**evaluation** lied to me, and how often the "obvious improvement" made things worse.

## The number I wanted to believe

The decision "bid, watch or skip" is the most valuable thing GigBid does. Bidding costs real money (Connects), so a
bad bid wastes it and a missed job is lost income. I labelled every job in my dev set with whether each freelancer
should bid, then measured my pipeline.

The first result was F1 = 0.92, with precision 0.996. I was pleased for about an hour.

Then I ran the same evaluation on the holdout split: a quarter of the jobs I had set aside and never looked at.
F1 = 0.51. Precision 0.36. GigBid was telling freelancers to bid on almost three jobs it should have skipped for every
one it got right.

Nothing was broken. I had fooled myself in an ordinary way. To keep the dev run fast I evaluated 150 jobs per
freelancer, and to make sure the interesting cases were included I sorted them so jobs worth bidding on came first.
That sample was nothing like the real stream, where most posts are not a fit for any given freelancer. Precision
looks wonderful when there are hardly any negatives to get wrong.

## Two leaks hiding behind the good number

Running the full dev set (2,208 job-freelancer pairs) reproduced the problem: F1 0.53, with 338 false bids. Reading
the false bids one by one turned up two causes.

**Leak 1: the agent was using sales pitches as proof.** The Fit Matcher checks each job requirement against evidence
retrieved from the portfolio. The portfolio includes 150 past proposals per freelancer, with outcomes. I had stored each
proposal with the skill tags *of the job it answered*, which is useful for learning what wins. But it meant that if the
freelancer had ever *pitched* for a "Data Analysis" job, "Data Analysis" now looked covered. Proposals are claims, not
evidence. Excluding them from fit (they still shape the writer's phrasing) took precision from 0.39 to 0.84.

**Leak 2: generic words earned partial credit.** A requirement like "Web Development" counted as partly covered if
the word "development" appeared anywhere in the retrieved text. Every portfolio contains "development". After a
small stop-list ("development", "data", "design", ...) the AI/ML engineer stopped looking like a 67% fit for a Webflow
design job.

I tuned these fixes on dev only, locked them, and ran the holdout once more: **F1 0.76**, precision 0.88, recall 0.67.
That is a worse headline than 0.92, and a much better system.

## "Improvements" that made retrieval worse

The same pattern showed up in retrieval. Before running anything I wrote down a hypothesis: *splitting a job into
its separate requirements and retrieving for each one will raise evidence recall by at least 10 points*. It sounds
right. A job asking for Python, a REST API and Celery is really three questions.

Decomposition alone **lowered** recall@5 from 0.593 to 0.560. A query like "Python" on its own matches every project;
the context that tied it to *this* job (the title, the other requirements) was gone, and fusing many weak result lists
diluted the strong one. It only paid off once combined with keyword search (BM25 finds "Celery" exactly where embeddings
blur it), a cross-encoder rerank, and grouping every vector of a project together.

That last step was the real win, and the reason is concrete. One synthetic project is a résumé-ranking API whose
case study never mentions Celery. The word appears in exactly one place: an `import celery` in the code. Indexing
code separately from READMEs and scoring a project by all its vectors found it. The best variant reached recall@5
0.648 and nDCG@10 0.697, against 0.593 and 0.578 for the naive baseline.

Then something slightly absurd happened. My linter, run with `--fix` across the repository, deleted that import as
"unused". The evidence vanished silently, and retrieval scores would have dropped with no code change. I only noticed
because I read the staged diff. There is now a test that fails if that import ever disappears.

One more "improvement" failed honestly: boosting evidence from projects whose past proposals won. It lowered recall
(0.630 to 0.606). Past wins track popular projects, not relevance to the job in front of you.

## A number that should not have survived

The proposal writer must never claim experience the portfolio does not support, so after drafting, a verifier splits
the proposal into claims and checks each against evidence before the critic sees it. I built a CI gate with a few
deliberately fabricated claims, and it failed on the first run.

The claim "I built a ticket classifier that routed **99%** of tickets automatically" was labelled *partly supported*
and kept. The evidence says 81%. The sentence is about the right project, so the relevance model scored it highly, and
my rule only rejected claims whose facts were *all* missing. A wrong number is the most damaging kind of fabrication,
because it is the most believable. Now any number the evidence does not contain makes the claim unsupported, however
relevant the rest of the sentence is.

## What I would tell someone starting this

- **Evaluate on the distribution you will deploy into.** Stratified samples are great for debugging and terrible for
  headline numbers. Keep a holdout and touch it rarely.
- **Read your false positives.** Both leaks were obvious after twenty minutes of reading examples and invisible in the
  aggregate.
- **Write the hypothesis down first.** Mine was wrong, and having written it is what made the negative result useful
  instead of embarrassing.
- **Make the boring parts deterministic.** Scam detection, bid rules, pricing and policy compliance in GigBid are
  plain configurable code, not LLM calls. They caught all 72 planted scams and all 45 injected posts across the dev and
  holdout sets at zero token cost. (The scams come from templates, so treat those numbers as optimistic.) A prompt injection
  cannot move money because no model holds a tool that can.
- **Your budget is part of the design.** Groq's free tier allows 200,000 tokens per model per day, and a single
  proposal with two critic revisions costs about 25,000. My first token budget per job (12,000) halted 40% of real
  runs before they reached a human. The fix was to measure the budget, not guess it.

The system I am proudest of is not the one with the best number. It is the one where every number points to a file,
and the file says what actually happened.

*Code, result files and the live demo: github.com/armsihh/agentic-gigbid-A2.*
