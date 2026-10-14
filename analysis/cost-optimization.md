# Jev cost and coverage experiments

The original scan costs about **$0.02357/question**. Complete-section scans
reduce that to **$0.00478** while including every extracted text unit. A
six-question bundle costs **$0.011253 total**, an allocated **$0.001875/question**:
approximately **12.6 times cheaper** than the original.

The app now defaults to complete sections, caches repeated exact questions,
and independently surfaces keyword source matches. New paid experimentation
cost **$0.296486**, below the $0.40 cap. Previously recorded responses were
reused when possible. The key was loaded at runtime without exposing it.

## Billing and methods

Jev bills input tokens, not a fixed fee per HTTP request. A batch pays for its
shared state once plus its questions. Our initial format repeated a long
instruction, structured keys, heading paths and parent text for each of 1,430
candidates. Larger HTTP batches do not remove that repeated question content.
[Billing/context specifications](https://docs.typesafe.ai/models),
[shared-state batching example](https://docs.typesafe.ai/cookbooks/parallel_questions).

Six queries covered brakes, EV shutdown, cockpit/egress, regeneration versus
hydraulic brakes, carbon-fibre grounding, and nyloc/Loctite brake fasteners.
Costs use provider-reported input tokens at the configured $0.042/million;
output is free. All strategies used four network workers.

- **Original per-rule scan:** about $0.02357/question, 13 requests.
- **Shorter per-rule prompts:** about $0.00897/question, six requests. It
  dropped 10 of 24 brake controls. Rejected as the default.
- **Shared context, per-rule questions:** about $0.00983/question, 36 requests.
  Better on brakes, but still dropped controls elsewhere.
- **Section-descriptor cascade plus keyword/reference expansion:** about
  $0.00543/question. Its candidates contained the controls, but the final
  per-rule classifier still dropped some.
- **Complete-section full scan:** about $0.00478/question, 32 requests,
  2.3–2.5 seconds. Every text unit is included. A single score covers a
  complete section-sized group; every numbered clause travels together.
  There are 506 groups, including substantive article introductions and tables,
  representing all 1,430 original text units.
- **Article-outline cascade, route threshold 0.1:** about $0.00538/question.
  It retained 1,005–1,338 units, so routing overhead cancelled much of the saving.
- **Article-outline cascade, threshold 0.5 plus local/reference expansion:**
  about $0.00276/question, 11–19 requests, 1.0–1.9 seconds. It checked only
  171–557 units and excluded some meaningful source material. It is an
  explicit selective mode, not the default.
- **Six-question complete-source bundle:** 267,921 input tokens,
  **$0.011253 total**, 32 requests, **2.983 seconds** for all six questions.
  The mean $0.001875/question is an allocation of the measured total, not
  separately reported usage for each question.

Bundles share each source chunk across different questions. Each question owns
its query inside its instructions; other queries are not added to its shared
state. This helps with a list ready together. Individual users are not delayed
to assemble bundles.

## Coverage findings

The original positive-control set had **53 rule/query checks**, involving 48
distinct entries. The original scan passed 47/53. Complete-section scoring and
the six-question bundle passed 53/53 at a 0.5 section threshold. Seeing the
complete corpus alone does not establish recall: the classifier can still
reject relevant clauses.

Error review added three cross-chapter checks:

- `F.8.6.3`: pedal clearance from the Anti Intrusion Plate, Front Bulkhead
  structure and non-crushable components, located in chassis rules.
- `IN.11.2.1`: no fluid leakage in the tilt test, including brake fluid.
- `EV.10.6.2`: Ready to Drive requires engagement of the mechanical brakes.

For the brake query, full-section scores for chassis clearance and the tilt
test were only 0.29 and 0.17; bundle scores were 0.17 and 0.06. A fixed model
threshold can therefore still hide source material. Simply lowering it returns
hundreds of weak matches.

Production results include ranked complete sections, a lower-score view, and
an **independent free SQLite search with engineering term expansions** that
Jev cannot veto. Brakes expands to pedal, hydraulic, reservoir and fluid terms.
The hidden chassis-clearance section appears as the second additional source
match for the brake sample.

With that independent check, all **56 exploratory checks** (51 distinct
entries) appear in primary or supplemental source sections for both the full
scan and bundle. The three extra checks were identified during error review;
this is not a held-out evaluation. Controls are in
[relevance-controls.json](relevance-controls.json).

**Exhaustive recall and precision remain unmeasured.** The control set is small,
there is no complete negative-label set, and the synonym glossary covers the
tested topics. An unseen relevant section can still score low. Figures remain
linked PDF content. Before using the tool as a complete requirements checklist,
expand the reviewed query set with real team questions and audit omissions
across chapters.

## Operating cost

For 20–30 people asking ten questions/day, with no cache hits:

- Original: **$4.71–$7.07/day**.
- Individual complete-section scans: **$0.96–$1.43/day**.
- Six-question bundles like the benchmark: **$0.38–$0.56/day**.

At an illustrative 180 usage days, these are about $849–$1,273,
$172–$258, and $68–$101. Projections assume the measured query lengths and
configured price. Bundle savings require questions supplied together.

An exact repeated question costs **$0 in new Jev usage**. The cache is shared
across users of one backend, capped at 256 entries, and tied to source, model,
prompt, strategy and vehicle context. It normalizes whitespace but preserves
case (`mV` and `MV` differ). Display count/threshold changes reuse decisions;
failed scans are not cached. A hypothetical 50% hit rate halves paid-query
cost, but no team hit rate has been measured. Rule-ID lookup and local search
also cost zero.

## Implementation and evidence

The browser defaults to complete-source sections. Selective routed mode shows
its coverage count. Results include source supplements, lower-score sections,
diagram flags and PDF links. Six measured full-section scans seed the cache.
Original per-rule mode remains available for comparisons.

`search-many` supports up to eight questions supplied together and reports
shared measured usage plus allocated mean cost. It makes a fresh bundle;
bundled decisions are not silently substituted for single-query cache entries.

Full results and the spend ledger are in `.cache/optimization/`, including
`bundle.json`.
The running cached semantic endpoint and PDF delivery were checked without
new paid requests.
