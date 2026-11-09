# What we measure, and why

Two stores, because two different questions.

| | `eval_run` / `eval_result` | `query_log` |
|---|---|---|
| Written by | `rfc_rag.evaluation.run` | every call to `ask()` |
| Needs gold labels | yes | no |
| Answers | "did this change make it better?" | "what is it doing in the wild?" |
| Rows | one per benchmark run | one per question asked |

**recall@5 belongs only in the left column.** It needs a known-correct answer,
and you do not have one for a live user's question. Any dashboard claiming
production recall is either replaying a fixed set or guessing.

---

## Retrieval metrics (benchmark only)

| Metric | What it answers | Kept? |
|---|---|---|
| **doc recall@1 / @5 / @10** | is the authoritative RFC in the top k | yes — @5 is the headline |
| **MRR** | how high it ranks, averaged | yes — moves when @k does not |
| section recall@k | the exact right section | advisory only |
| nDCG@k | graded relevance, rank-discounted | **no** |
| precision@k | how much of the output was relevant | **no** |

**Why section recall is advisory.** Gold sections are chosen by embedding
similarity *within* the correct document, which is circular — the thing being
measured helped pick the answer. Only the document-level number is independent,
because the gold document was named from domain knowledge before any search ran.

**Why no nDCG.** It exists for graded relevance — "this result is a 3, that one
is a 1". Ours is binary: the right RFC or not. With binary labels and one gold
item, nDCG is a rank-discounted restatement of MRR. Two numbers that always
agree is one number and a false sense of rigour.

**Why no precision@k.** With one or two gold items out of 9,572 sections,
precision@5 is capped at 0.4 no matter how good retrieval is. It would mostly
measure how many gold items I wrote down.

**Keep both recall@5 and MRR**, though, because they disagree usefully.
Reranking that moves the answer from 5th to 1st leaves recall@5 unchanged and
lifts MRR — and the user feels that difference.

## Answer metrics (benchmark only)

| Metric | Definition | Why |
|---|---|---|
| `answer_rate` | answered / answerable | catches a system that refuses its way to safety |
| `correct` | expected fact present / answered | the only metric that measures being right |
| `grounded` | quote verified / answered | hallucination rate, inverted |
| `cited_right` | cited the authoritative RFC / answered | right answer from the wrong document is luck |
| `false_refusal_rate` | refusals on answerable / answerable | the cost of being cautious |
| `refusal_accuracy` | correct refusals / unanswerable | the benefit of it |

**The last two must be read together.** Either is trivially gamed alone — always
answer, or always refuse. A change that lifts refusal accuracy from 0.70 to 0.90
while false refusals go 0.03 to 0.20 is a regression wearing a win.

`correct` here is a substring check (`expect` in `eval/questions.py`). It is
lenient — "What is an SVCB record?" passes on the word "service". It proves
answers are not wildly wrong, not that they are right. Stated rather than
dressed up.

## Cost and latency (both stores)

`p50_ms`, `p95_ms`, `tokens_in`, `tokens_out`, `llm_calls`.

p95 rather than mean: averages hide the bad experiences, and the slow tail is
what people remember. `llm_calls` divided by questions is the cost metric that
matters here — fact and passage routes answer with zero calls, so driving that
ratio down is the cheapest optimisation available.

Token counts come from `llm.last_usage`, which only the `direct` backend
populates. Framework backends leave those columns null.

## What production can actually tell you without gold labels

- **Grounding rate.** The quote check is a string comparison, so it works on
  live traffic. **This is the one quality metric that survives without gold
  labels**, and it exists only because verification is mechanical rather than a
  model judging a model.
- Route distribution — how much traffic avoids the model.
- Refusal rate — a spike means the corpus or retrieval moved.
- Latency percentiles and token spend.
- Retrieval score distribution — a drifting top-1 score suggests the questions
  being asked have changed.
- Repeated questions — the natural source of new eval cases.

## Deliberately not measured

- **BLEU / ROUGE.** Similarity to a reference answer. There is no reference
  answer, and phrasing is not the thing under test.
- **LLM-as-judge scores.** Would be needed for "does the quote support the
  claim", but an unvalidated judge is an opinion with a decimal point. If added,
  its agreement with human labels has to be measured first.
- **Embedding drift / silhouette scores.** Diagnostics for a problem we do not
  have.

## Regression tracking

Each run stores the git SHA, whether the tree was dirty, the corpus size, the
model and backend, and one row per question. So a change is comparable rather
than remembered:

    uv run python -m rfc_rag.evaluation.run "after adding reranking"

prints the deltas against the previous run and names every question that was
right before and is wrong now — which is more useful than any aggregate,
because it is the list you actually go and fix.
