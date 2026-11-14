# Change request: the 2 November 2026 platform policy update

The assignment announced a GigSim "platform policy update" introducing "a new rule or cost affecting bidding". No update
was released to the class, so I wrote one that touches both a **cost** and a **rule**, applied it on the platform side
(as the instructor's GigSim update would), and measured what absorbing it cost GigBid.

## The update (`gigsim/policy_2026-11-02.yaml`, enable with `GIGSIM_POLICY_FILE`)
1. **New cost:** jobs with 50+ applicants cost **+4 Connects** to bid on.
2. **New rule:** cover letters may not exceed **1,500 characters** (was 5,000). GigSim rejects longer drafts with
   `422 cover_letter_length`.

Platform side: `gigsim/world.py` +4 lines (generic surcharge rules read from the policy file) and the new policy file.

## What GigBid had to change: 12 lines in 5 files, 1 config value
| File | Change | Lines |
|---|---|---|
| `agent/config.yaml` | `compliance.proposal_length: {min_words, max_words, max_chars: 1500}` | +1 |
| `agent/prompts/writer.md` | the hard-coded "120-220 words" became `{length_rule}` | +1 / -1 |
| `agent/nodes/writer.py` | render `length_rule` from config | +3 / -1 |
| `agent/nodes/critic.py` | `length_ok` uses the configured words and characters | +2 / -1 |
| `agent/nodes/compliance.py` | block drafts over the configured length (`concise_proposals`) | +2 |
| `agent/nodes/pricing.py` | **nothing**: it already prices with the marketplace's per-job Connects cost, so the surcharge flows into the expected-value check | 0 |

Time: about 25 minutes, including the test (`tests/integration/test_change_request.py`), which checks that the
platform charges +4 on a crowded job, GigBid's pricing sees it, GigSim rejects a 2,300-character letter, and Compliance
blocks it before it is ever sent.

## What it says about the design
- **Costs were already data.** Pricing never assumed a Connects price; it reads the job's cost from the marketplace and
  compares expected value against a configured threshold. A new surcharge is invisible to the code.
- **One length rule was hard-coded in three places** (writer prompt, critic, nothing in compliance). That was the real
  cost of the update and the lesson: every platform rule a node depends on now lives in `agent/config.yaml`, read by
  every node that needs it. A future change to the length limit is a one-line config edit.
- **Compliance is the backstop.** Even if a prompt change were missed, the deterministic Compliance Guard blocks a
  non-conforming draft with a visible reason instead of letting the marketplace reject it after approval.
