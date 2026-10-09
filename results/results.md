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
