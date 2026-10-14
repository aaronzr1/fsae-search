# Initial live Jev sample runs

Ran on 14 October 2026 against the complete 2027 V1 text index. Each query
evaluated all 1,430 candidates, using four HTTP workers and 13 native batches.
All 39 requests returned HTTP 200, every evaluation produced a valid answer,
and no retries or batch splitting were necessary. Model: `jev-1.13.0`.

- **Brakes:** 2.431 seconds; 561,137 input tokens; 28,972 output tokens;
  56 matches at threshold 0.5; **$0.023568**. Results cover T, IN, EV, IC, F and D.
  High-ranking matches include T.3.1.3, T.3.1.2, T.3.1.7, T.3.2.3 and IN.14.1.
- **EV shutdown circuit:** 2.557 seconds; 561,176 input tokens; 28,972 output tokens;
  71 matches; **$0.023569**. EV.8.1.1, EV.8.1.5 and EV.8.2.2 lead the results.
- **Cockpit opening and driver egress:** 2.022 seconds; 561,189 input tokens;
  28,972 output tokens; 12 matches; **$0.023570**. Results include IN.9.2.1,
  IN.9.2.2, T.1.1.2, and diagram-bearing rules T.1.1.1 and T.1.2.1.

Total: **1,683,502 input tokens**, 86,916 output tokens, and **$0.070707**.
Usage values come from the provider responses; costs multiply reported input
tokens by the configured $0.042 per million price. Output is free at the
[documented model price](https://docs.typesafe.ai/models).

Full decisions, scores, references, source links, per-request timing and usage
are saved in [sample-queries.json](../.cache/sample-queries.json). This is one
trial per query, not a measured recall/precision evaluation or a latency SLA.
The score threshold is an initial setting. Diagrams remain linked PDF content
and are not interpreted by Jev.
