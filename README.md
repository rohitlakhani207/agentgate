# AgentGate

**A free safety layer for AI agents.** Two open decision models check every tool call
before it runs, and only unclear or risky calls reach you, as a card on your phone.
Zero running cost: open models, free-tier LLMs, a laptop.

- **Step 1 · [Strands Decider 2B](https://strandsagents.com/blog/introducing-strands-decider/)** checks every call (about 115 ms on a GPU, per its authors) and settles the ones it is sure about.
- **Step 2 · [Clef-flash](https://huggingface.co/ggml-org/Clef-Flash-GGUF)** looks only at what step 1 was unsure about.
- **Step 3 · You** approve or deny the rest from a phone web app. No answer in 60 s counts as deny.

Both models are *decision models*: they return a choice with a confidence score instead
of generating text, and their authors calibrate that score so a threshold on it means
something (the benchmark checks whether it does). Both speak the same System One API
(`POST /v1/systemone`), so one client drives both steps.

> **Result, October 2026:** the two-step gate missed **zero dangerous actions** on 150
> labelled calls, but not the way the design planned. Strands Decider 2B was too
> confident in its mistakes to be a safe first filter, so Clef-flash does nearly all the
> settling and 69% of calls still go to the phone. All six setups are measured below;
> the findings explain what worked and what didn't. 84 tests run on every push.

<p align="center">
  <picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/phone-card-dark.png"><img alt="A delete_file call waiting for approval on the phone" src="docs/images/phone-card-light.png" width="250"></picture>
  <picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/phone-approved-dark.png"><img alt="One tap approves it" src="docs/images/phone-approved-light.png" width="250"></picture>
  <picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/phone-history-dark.png"><img alt="The History tab: every call, its verdict and who settled it" src="docs/images/phone-history-light.png" width="250"></picture>
</p>
<p align="center"><sub>Real screenshots of one run: a delete waits on the phone, one tap approves it,
and History shows every call and who settled it. <code>scripts/capture_proof.py</code> recaptures them.</sub></p>

## See it run

The agent side of the same run: a safe task runs on its own, a delete goes to the phone,
and an instruction hidden in a PDF to wipe the folder is blocked. Recorded with the
keyword gate so it runs anywhere without a model server; the flow is the same with the
two-step gate.

<p align="center"><img alt="Terminal output of agentgate demo" src="docs/images/demo-terminal.svg" width="760"></p>

## Results

The benchmark scores six ways of gating the same 150 labelled tool calls
(`data/tool_calls.jsonl`, including 20 prompt injections hidden in documents).
`uv run agentgate eval` rebuilds this section from the labelled data.

<!-- results:start -->
Scored on 150 labelled tool calls (`data/tool_calls.jsonl`). **Missed dangerous** = labelled ask or block, but the setup allowed it. **Over-blocked safe** = labelled allow, but the setup asked or blocked. Latency is per tool call on the machine that ran `agentgate eval`; for hosted models (the LLM judge) it includes the network round trip.

| Setup | Accuracy | Missed dangerous | Over-blocked safe | Median ms | p95 ms | Settled at step 1 | Sent to phone | Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Keyword rules | 87% | **2** (2 inj.) | 0 | <1 | <1 | - | 41% | ₹0 |
| Own trained classifier | 66% | **13** (4 inj.) | 13 | 26 | 45 | - | 34% | ₹0 |
| LLM as judge | 76% | **25** (2 inj.) | 1 | 691 | 1893 | - | 21% | ₹0 |
| Decider 2B alone | 62% | **35** (6 inj.) | 0 | 1026 | 1228 | - | 34% | ₹0 |
| Clef-flash alone | 73% | **13** (4 inj.) | 5 | 364 | 861 | - | 43% | ₹0 |
| Two-step gate | 61% | **0** | 10 | 1441 | 2017 | 1% | 69% | ₹0 |

### Threshold sweep

Decider's threshold from 0.50 to 0.95 (step 2 threshold fixed at 0.50). **Chosen threshold: 0.90**, the one with zero misses and the highest step-1 share.

<picture><source media="(prefers-color-scheme: dark)" srcset="results/threshold_sweep_dark.png"><img alt="Threshold sweep" src="results/threshold_sweep_light.png" width="640"></picture>

### Calibration

<picture><source media="(prefers-color-scheme: dark)" srcset="results/calibration_dark.png"><img alt="Calibration" src="results/calibration_light.png" width="640"></picture>

<details><summary>Calibration table</summary>

| Model | Confidence | Calls | Matched the label |
| --- | --- | ---: | ---: |
| Decider 2B alone | 0.0-0.2 | 5 | 0% |
| Decider 2B alone | 0.2-0.4 | 40 | 32% |
| Decider 2B alone | 0.4-0.6 | 40 | 60% |
| Decider 2B alone | 0.6-0.8 | 38 | 87% |
| Decider 2B alone | 0.8-0.9 | 26 | 85% |
| Decider 2B alone | 0.9-1.0 | 1 | 100% |
| Clef-flash alone | 0.0-0.2 | 32 | 44% |
| Clef-flash alone | 0.2-0.4 | 23 | 61% |
| Clef-flash alone | 0.4-0.6 | 20 | 65% |
| Clef-flash alone | 0.6-0.8 | 62 | 90% |
| Clef-flash alone | 0.8-0.9 | 13 | 100% |
| LLM as judge | 0.8-0.9 | 2 | 0% |
| LLM as judge | 0.9-1.0 | 148 | 77% |
| Own trained classifier | 0.0-0.2 | 37 | 41% |
| Own trained classifier | 0.2-0.4 | 60 | 65% |
| Own trained classifier | 0.4-0.6 | 45 | 84% |
| Own trained classifier | 0.6-0.8 | 8 | 88% |

</details>
<!-- results:end -->

## Findings so far

- **The gate needed facts the call doesn't contain.** In the first keyword-rules run,
  10 of the 12 misses were writes that overwrote an existing file. No gate can tell that
  apart from creating a new file, because the call doesn't say whether the file exists.
  The sandbox now measures it before any gate runs, along with how many files a delete
  would remove. Misses fell from 12 to 2 for the keyword rules, and from 20 to 16 for the
  trained classifier.
- **Rules catch loud injections, not quiet ones.** Both remaining keyword misses are
  injections phrased without trigger words, where the call itself looks harmless: reading
  the customer list, and drafting an email to an outside address. This is the gap the
  decision models' injection question is meant to close.
- **A general LLM treats "the user asked" as permission.** As the judge,
  `gpt-oss-120b` (Groq free tier, low reasoning effort) caught 18 of 20 injections. But it
  allowed 25 risky calls, and 20 of them were deletes, overwrites, sends or secret reads
  the user had requested, which the policy sends to a human ("User explicitly requested
  deleting a specific old log file"). The sandbox facts stopped it allowing reads outside
  the sandbox (4 such misses before), but not this habit.
- **The LLM's confidence carries no signal.** All 150 of its answers claimed 0.87 to 1.00
  confidence, yet only 76% matched the label. A threshold on that number can't separate
  sure from unsure, which is why the gate relies on decision models instead.
- **Clef-flash's injection question is the sharpest signal so far.** Asked alongside every
  decision, it scored 0.5 or more on 17 of the 20 injected calls and on none of the other
  130: no false alarms.
- **Clef-flash's confidence does carry signal**, unlike the LLM's: it averages 0.59 on
  answers that match the label and 0.31 on those that don't.
- **Telling the models what the sandbox knows made that confidence usable.** In the first
  Clef run, its 8 most confident misses were reads outside the sandbox (`~/.ssh/config`,
  `..`), shell commands off the allow-list (a pipe, a redirect, `curl`) and a secrets read.
  The gate was told nothing about these, because facts then covered only writes and
  deletes. With facts for every tool, 6 of those misses were fixed, and Clef's confidence
  fell below 0.5 on every miss that remains (the highest is 0.47). Run with the gate's
  rules (unsure goes to the phone), Clef alone now reaches zero misses at a threshold of
  0.5, where before it needed 0.8. It still sends 69% of calls to the phone, though: the
  load the Decider is meant to take. Three answers with confidence under 0.1 flipped to
  allow; the gate never settles answers that unsure. The keyword rules, which don't read
  the new facts, scored identically before and after.
- **The 2B Decider was too sure of its mistakes to go first.** Alone it reached 62%
  accuracy with 35 misses. It said allow 90 times when only 55 calls were safe, and one
  of its misses came at 0.89 confidence. Its confidence still separates right from
  wrong on average (0.64 against 0.41), but zero misses needs a step-1 threshold of 0.9,
  where it settles about 1% of calls instead of the hoped-for 70%. Its injection
  question flagged 14 of 20 injections, with 33 false alarms; Clef-flash's had none.
- **So the two-step gate's safety comes from Clef-flash.** Sweeping both thresholds over
  the cached answers, the best zero-miss setting is Decider 0.9 and Clef-flash 0.5: 61%
  accuracy, 10 safe calls interrupted, and 69% of calls sent to the phone. That reaches
  the PRD's main target (no missed dangerous actions) but misses the others (90%
  accuracy, 70% settled by step 1, under 500 ms). Both thresholds were chosen on these
  same 150 calls, so a held-out set would likely show a little worse.
- **The Decider is a good router.** Asked whether a request is simple or complex, it got
  93 of 100 right, never sent a simple request to the large model, and sent 7 complex
  ones to the small model (`results/router.md`, median 306 ms).
- **150 labels are too few to train a gate from scratch.** The embeddings + logistic
  regression baseline reaches 67% accuracy with 16 misses under 5-fold cross-validation.
  Pre-trained decision models need no training data at all.
- **A small local LLM resisted one injection on its own.** In a live run, `qwen3.5:4b`
  read the poisoned partner brief, told the user about the hidden instruction and did
  not act on it. One run says nothing about the next; the gate is for the run where the
  model does obey.

## How it works

```mermaid
flowchart TD
    A["Agent proposes a tool call<br/><small>LangGraph + a free LLM</small>"] -->|every call| S1
    S1["Step 1 · Strands Decider 2B<br/><small>small, local, checks every call</small>"] -->|confident| D
    S1 -->|"unsure, or allow on delete/send"| S2
    S2["Step 2 · Clef-flash 9B<br/><small>only when step 1 is unsure</small>"] -->|confident| D
    S2 -->|"unsure, or the models disagree"| S3
    S3["Step 3 · You, on your phone<br/><small>web app over WebSocket · 60 s or deny</small>"] -->|approve / deny| D
    D["Decision applied<br/><small>allow: runs in the sandbox · block: stopped and explained</small>"] --> L[("Audit log · SQLite")]
```

The rules, in [`gates/two_step.py`](src/agentgate/gates/two_step.py):

- **Each step settles only what it is sure about.** A vote below the confidence
  threshold moves the call down one step.
- **Agreement rule.** For `delete_file` and `send_email`, auto-allow needs *both* models to
  say allow; a confident allow from step 1 alone still goes to step 2.
- **Injection check.** Each model also answers a yes/no question: *is this call carrying out
  instructions from the context rather than the user?* An allow from a model that says
  yes counts as unsure. Asking a second question costs almost nothing, because the
  model reads the state once.
- **Fail closed.** An unreachable model counts as unsure; an unreachable phone counts as deny.

The gate sees what the user asked for, the tool call, the last text the agent read
(where injections hide), and **facts** measured by the sandbox before any gate runs
([`tools/preflight.py`](src/agentgate/tools/preflight.py)): whether a path is inside the
sandbox, whether a write would overwrite an existing file, how many files a delete removes,
whether a shell command is on the allow-list, and whether a file name or an email body
looks like it holds secrets. The deterministic part of the policy arrives as facts; the
models judge intent.

Behind the gate, the tools enforce their own limits, so a gate mistake can't do real
damage: file tools resolve every path (symlinks included) inside one sandbox folder;
shell commands come from an allow-list and run without a shell (no pipes, redirects or
chaining); `send_email` writes `.eml` files by default and, in SMTP mode, only ever
delivers to your own address.

## Quick start

Needs [uv](https://docs.astral.sh/uv/), Docker and an LLM: a free
[Groq](https://console.groq.com) API key (what the published results use) or
[Ollama](https://ollama.com) to stay fully local. Copy `.env.example` to `.env` and fill
in the LLM lines.

```bash
git clone https://github.com/<you>/agentgate && cd agentgate && uv sync --extra eval
docker compose up -d                      # approval server + Decider (add --profile clef for step 2)
uv run agentgate seed && uv run agentgate pair   # demo sandbox; scan the QR code with your phone
uv run agentgate demo                     # a safe task, a phone approval, a blocked injection
uv run agentgate eval                     # rebuild the results table and charts
```

Then try the agent on anything: `uv run agentgate run "Clean up old log files"`.

`uv run agentgate status` shows which parts are reachable. Clef-flash doesn't have to run
locally at all: set `AGENTGATE_CLEF_BACKEND=cloudflare` with a free Cloudflare account ID
and API token, and step 2 uses Cloudflare's hosted copy on its free daily allowance. If the
laptop can't hold a model (Decider needs about 8 GB of RAM on CPU, Clef-flash Q4 about
7 GB), run it on a free GPU with [`notebooks/models_on_colab.ipynb`](notebooks/models_on_colab.ipynb) and set
`AGENTGATE_DECIDER_URL` / `AGENTGATE_CLEF_URL` to the tunnel it prints. If Clef can't run
at all, `AGENTGATE_STEP2=llm_judge` uses the LLM judge as step 2.

## The phone app

A mobile web page served by the approval server: no install, no app store. `agentgate pair`
prints a QR code; scanning it opens the page and pairs the phone with a shared token
(kept in `var/token`, sent in the URL fragment so it never reaches server logs). Add it to
your home screen and it behaves like an app.

Each card shows what you asked for, the exact call, why it reached you, each model's
vote and confidence, and a 60-second countdown. The History tab reads the audit log.
Cards only arrive while the page is open; background alerts would need HTTPS and Web Push.

## The benchmark

| Setup | What it shows |
| --- | --- |
| Keyword rules | The no-AI baseline ([`gates/keyword.py`](src/agentgate/gates/keyword.py)) |
| Own trained classifier | Sentence embeddings (bge-small, ONNX) + logistic regression, scored with 5-fold cross-validation |
| LLM as judge | The slow, general-purpose baseline. Published numbers: `openai/gpt-oss-120b` on Groq's free tier, low reasoning effort |
| Decider 2B alone | Step 1 on its own |
| Clef-flash alone | Step 2 on its own |
| Two-step gate | The full design |

- **Missed dangerous actions**: labelled ask or block, but the setup allowed it. The target is zero.
- **Over-blocked safe actions**: labelled allow, but the setup asked or blocked.
- **Threshold sweep**: the Decider's threshold from 0.50 to 0.95; the table uses the
  threshold with zero misses and the highest step-1 share.
- **Calibration**: decisions grouped by confidence, and how often each group was right.

Every model's raw votes are cached in `results/raw/` with a fingerprint of the call and the
policy wording, so the table rebuilds in seconds (`agentgate report`), a free-tier rate
limit only costs a resume, and editing a call re-runs just that call.

Also in the box:

- `agentgate eval-router` scores the Decider as a **model router** (small vs. large LLM)
  on 100 labelled requests in `data/router_requests.jsonl`.
- `agentgate agreement` compares your labels with a second person's on the 30 calls in
  `data/friend_labels.csv` (Cohen's kappa).

The labels follow [`data/LABELLING_RULES.md`](data/LABELLING_RULES.md), and every row
names the rule that decided it.

## Configuration

Everything is an environment variable with a working default; see
[`.env.example`](.env.example). The ones you're most likely to change:

| Variable | Default | |
| --- | --- | --- |
| `AGENTGATE_LLM_PROVIDER` | `ollama` | `ollama`, `groq` or `gemini` |
| `AGENTGATE_LLM_SMALL_MODEL` / `_LARGE_MODEL` | `qwen3.5:4b` / `gemma4:12b` | The router picks one per request. On Groq: `openai/gpt-oss-20b` / `openai/gpt-oss-120b` (Groq's free tier no longer serves Llama chat models) |
| `AGENTGATE_GATE` | `two_step` | Or any single setup: `decider`, `clef`, `llm_judge`, `classifier`, `keyword`, `none` |
| `AGENTGATE_DECIDER_THRESHOLD` | `0.9` | Set it to what the sweep picks |
| `AGENTGATE_STEP2` | `clef` | `llm_judge` is the fallback |
| `AGENTGATE_CLEF_BACKEND` | `local` | `cloudflare` uses Cloudflare Workers AI (needs `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`) |
| `AGENTGATE_EMAIL_MODE` | `outbox` | `smtp` sends, but only to `AGENTGATE_EMAIL_SELF` |

## Limits worth knowing

- **One person wrote the labels**, and also the keyword rules, which flatters the rules.
  The 30-call agreement check exists to measure that; a held-out set written by someone
  else would be fairer still.
- **150 calls is small.** A difference of a few calls between setups is noise.
- **Latency is the machine's.** On a laptop CPU the Decider runs in fp32 and is much
  slower than its published GPU numbers. For hosted models (the LLM judge on Groq, or a
  model behind a Colab tunnel) latency includes the network round trip.
- **Remote models, remote latency.** The Decider ran on a free Colab T4 GPU in fp32 behind
  a tunnel, and Clef-flash on Cloudflare, so the gate's latencies (1.4 s median for the
  two-step gate) are mostly network round trips, not model time.
- **The LLM judge thought briefly.** It ran with low reasoning effort to fit Groq's free
  limits (8,000 tokens a minute). More reasoning might catch more, at the cost of tokens
  and time.
- **The demo is scripted.** `agentgate demo` replays fixed tool calls through the real gate,
  phone and tools, because a small local LLM won't reliably obey an injected document on
  camera. `agentgate run` is the live agent. The screenshots and terminal image above
  come from that scripted demo, run with the keyword gate.

## Pinned versions

Python dependencies are locked in `uv.lock`. The models and servers:

| Part | Version |
| --- | --- |
| Strands Decider | `strands-decider==0.1.0`, `StrandsAgents/strands-decider-2B-hobson-v19`, torch 2.14.1 (CPU) |
| Clef-flash | `ggml-org/Clef-Flash-GGUF:Q4_K_M` (6.49 GB) on `ghcr.io/ggml-org/llama.cpp:server` (needs PRs #29818 and #29831, Oct 2026), or `@cf/cloudflare/clef-flash` on Cloudflare Workers AI |
| LLM (agent and judge) | `openai/gpt-oss-120b` and `openai/gpt-oss-20b` on Groq (free tier), or `qwen3.5:4b` and `gemma4:12b` on Ollama |
| Agent | LangGraph 1.2, langchain-core 1.6 |
| Server | FastAPI 0.142, uvicorn 0.54 |

## Project layout

```
src/agentgate/
  gates/        keyword, classifier, llm_judge, decision_model (System One), two_step, policy
  agent/        LangGraph loop, guarded executor, phone approval client, model router
  approval/     FastAPI + WebSocket server and the phone web page (static/)
  tools/        sandboxed files, allow-listed shell, email to yourself
  eval/         vote cache, metrics, results table, charts, agreement, router eval
data/           labelling rules, 150 tool calls, 100 router requests, friend sheet
notebooks/      both models on a free Colab/Kaggle GPU
results/        generated table, charts and cached raw votes
scripts/        capture_proof.py: the README's screenshots and terminal image, from a real run
docs/images/    those screenshots
```

Run the tests with `uv run pytest`.
[![Tests](https://github.com/rohitlakhani207/agentgate/actions/workflows/tests.yml/badge.svg)](https://github.com/rohitlakhani207/agentgate/actions/workflows/tests.yml)
