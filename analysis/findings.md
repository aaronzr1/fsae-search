# FSAE 2027 V1: rule indexing and Jev feasibility

Examined the supplied 147-page [rulebook](../FSAE_Rules_2027_V1.pdf), dated 1 September 2026. This is an analysis of that specific edition, not a claim that it is the latest published edition. Counts are reproducible with `examine_rulebook.py`; complete extracted data is in `rulebook-index.json` and count/packing evidence is in `statistics.json`.

## How many rules?

There are **1,825 unique numbered entries**: 103 articles (`F.5`), 488 sections (`F.5.6`), and 1,234 paragraphs (`F.5.6.5`), under 12 categories. These include headings, definitions, procedures, scoring provisions, and requirements.

There are **1,398 terminal numbered entries**, meaning entries with no numbered descendants. One, `IC.2.1 General` on page 81, is an empty heading in the source. That leaves **1,397 terminal entries with substantive text**. This is the useful leaf count, but it does not count individual engineering constraints: one entry can contain several lettered clauses, bullet requirements, exceptions, and notes.

Searching only the 1,234 deepest paragraphs would omit 162 terminal sections and two terminal articles. Conversely, searching every article with its entire subtree would repeat large amounts of text and return broad headings alongside precise rules.

Recommended initial candidate inventory: **1,430 search units** = 1,397 substantive leaves + 31 parent introductions with their own substantive text + two standalone tables (`PS-1` and `PS-2`). Figures and formulas require source-region preservation and reviewed transcription before the corpus can claim complete semantic coverage.

The terminal counts by category are: GR 73, AD 48, PS 26, V 38, F 257, T 195, VE 32, IC 122, EV 236, IN 101, S 94, D 176. These counts include the empty `IC.2.1` heading.

Validation: all **591 numbered bookmarks** resolve to definitions on the correct PDF page; definitions are unique; an independent scan of numbered text produces the same 1,825 distinct IDs. The PDF prints `D.8.1.1` through `D.8.1.7` without a `D.8.1` heading. Preserve that numbering and attach the entries to the nearest actual ancestor, `D.8`, rather than fabricating an extra rule.

The extractor is deliberately specific to this edition's layout: numbered definitions start at the 72-point left margin; the first four pages and page footers are excluded. Future editions need these assumptions checked again. It is single-process and runs in the project virtual environment. To reproduce: `uv venv .venv`, `uv pip install --python .venv/bin/python -r analysis/requirements.txt`, then `.venv/bin/python analysis/examine_rulebook.py`.

## What should an indexed rule contain?

Use the numbered rule as the primary record. Keep lettered subclauses and bullets together so that prerequisites, alternatives, exceptions, and notes survive retrieval. Store distinct source spans for optional subclause highlighting later. A paragraph such as `F.4.2.6` crosses several logically related test conditions; splitting each sentence into an unrelated chunk would lose context.

The proposed [SQLite schema](schema.sql) separates:

- **Documents and categories:** edition, year, publication date, PDF hash, source URI, page count, extractor version, and ordered hierarchy. IDs must include document version; `EV.8.1.1` alone is not globally unique.
- **Rules:** official ID, kind, nearest actual parent, original numbered parent, order, optional official heading, and own text excluding descendants.
- **Source spans:** one-based PDF page, printed page label, text or region bounding boxes in PDF coordinates, and exact extracted text. Keep multiple spans for rules crossing pages.
- **Assets and rule-asset links:** standalone tables, figures, and formulas; source location; reviewed table rows or transcriptions; and whether the rule actually refers to the illustration.
- **Cross-references:** source, target, original reference string, optional lettered subclause, and extraction/review provenance. References can point to a rule, an asset, or an external supplement.
- **Annotations:** vehicle applicability, definitions, obligation type, and topic tags, with supporting evidence and review status. Use unreviewed tags for hints, not exclusion filters.
- **Search units and decisions:** a derived context-enriched candidate, content hash, prompt/context version, resolved Jev model, relevance score, and explicit error status.

The generated [JSON index](rulebook-index.json) is a concrete provisional extraction of the document, not just a schema example. It includes source line ranges, source regions, hierarchy, 550 explicit rule-reference occurrences representing 537 distinct directed edges, and the 1,430 candidate units. That reference count covers explicit rule IDs in rule bodies; it excludes references within standalone tables, unnumbered references such as “above,” and inferred dependencies.

Keep the canonical PDF as the source of truth. Derived search text should consist of the rule's own text plus its heading path and short parent introductory text. Referenced sections should be resolved on demand rather than repeatedly embedding whole sections into every candidate.

## Links back into the PDF

Each result can construct a browser link such as `/documents/{document_id}/source.pdf#page=105`, alongside the rule ID and heading path. The source URI should identify the exact hashed edition. A native browser PDF viewer opens the page; a custom viewer can use the stored bounding boxes to scroll to and highlight the rule while retaining the surrounding page.

For example, [EV.8.1.1 is on page 105](../FSAE_Rules_2027_V1.pdf#page=105). Its shutdown-component list points to `EV.8.3`, `EV.8.6`, `EV.8.7`, `EV.8.8`, `EV.8.9`, `EV.8.10`, `T.3.3`, and `T.9.4`. Display the matched rule first, then linked details with their own PDF positions. Incoming references are also useful: a generic switch rule may be relevant because the shutdown system points to it.

Store each page's source region, not only its first text box. `F.10.3.6`, for example, continues from page 51 to page 52. A page number alone cannot express that span, and the initial text box does not include diagrams below the prose.

## Can we copy Jev straight?

**Yes: a full-corpus, independent relevance scan is a reasonable first implementation for this corpus.** The model-facing layer from your existing `jev-imsg` project is reusable. A vector database and local query planner are optional at this size.

The current iMessage pipeline is actually planner → dense/BM25 retrieval → fusion → Jev over a shortlist. Its Jev layer already supports native question batching, bounded concurrent HTTP requests, retries, probability validation, per-candidate failures, provenance, and progress reporting. Reuse those mechanics. Replace the iMessage-specific candidate validator, message fields, timestamps/participants, and conversational-event question with a rule-specific adapter and relevance question.

Recommended flow:

1. Take the original query and optional vehicle type.
2. Send every eligible search unit through one independent Noul relevance question, using native batches.
3. Sort scores, retain an uncertain band, and group multiple units belonging to the same rule.
4. Expand references and parent context for the high-ranking matches. Keep directly scored matches distinguishable from related rules reached through references.
5. Return original rule text, heading path, relevance score, and PDF position; expose failed evaluations and whether the scan finished.

Ask whether a rule helps answer the query, including definitions, restrictions, exceptions, or tests. A rule prohibiting the user's proposed design is highly relevant. A prompt asking whether the rule “supports” that design would incorrectly suppress useful negative answers. Relevance scores are not compliance judgments.

Use independent **Noul** questions for a result list. A single Choice across all rules cannot handle the corpus: Choice is limited to 255 options, and its probabilities sum to one. Choice scores from separate groups are therefore not a common global relevance scale. [TypeSafe API reference](https://docs.typesafe.ai/api), [semantic-search cookbook](https://docs.typesafe.ai/cookbooks/semantic_find).

Put the small shared query in `state` and one rule plus its context in each question's structured `instructions`. That is supported by the API and matches the existing client's design. Avoid putting the entire rulebook in every request's shared state: unrelated text creates distractions and runs into the state-plus-question context budget. [Structured questions](https://docs.typesafe.ai/primitives/advanced), [documented failure modes](https://docs.typesafe.ai/model-jaggedness/jev-1.13).

## Workload, cost, and CPU

A dry pack using a representative EV battery-container query and relevance prompt, with the existing client's limits, yields:

- **1,430 comparisons**, packed into **28 HTTP requests**.
- **Four concurrent requests**, corresponding to seven groups of up to four batches. These are network workers; the Jev inference runs remotely. This keeps local CPU work modest on the eight-core machine.
- Maximum 100 questions or 60,000 JSON bytes per batch; 28,000 bytes per query/candidate pair. No pair in this extraction exceeds the pair limit.
- Approximately **1.63 MB of question JSON** across the scan. This is a payload-size measurement, not a provider token count.

TypeSafe currently documents `jev-1.13.0` at **$0.042 per million input tokens**, free output, with a 64k-token total request budget and a 32k-token budget for state plus the longest question. Published rate limits are dynamic. Pin the model during evaluation and log its resolved version. [Current model specifications](https://docs.typesafe.ai/models).

For illustration, if measured billed usage is 300,000–600,000 input tokens per full scan, it would cost approximately **$0.013–$0.025 per query** at that price. That token range is a planning assumption, not a measurement or tokenizer result. Actual cost must come from API `usage.input_tokens`, including the chosen prompt/context and retries.

There is **no measured latency or relevance accuracy yet**: this task made no authenticated Jev calls. Seven waves describe scheduling, not seconds. The live benchmark should record total latency, batch latency, provider usage, retries, errors, and the number of relevant rules found. More than four client workers should be considered only after observing a network or rate-limit bottleneck; additional local model processes are unnecessary for the initial full scan.

## Extraction limitations that matter

- **Vector diagrams:** page 56's cockpit-opening template has geometry and dimensions that ordinary PDF text extraction does not recover. The document has body vector paths on 66 pages, including tables, formulas, underlining, and figures; this is a review flag, not a count of diagrams. Jev currently accepts text only. Preserve PDF regions and transcribe important geometry before claiming semantic coverage of dimensions. [Model input formats](https://docs.typesafe.ai/models).
- **Standalone tables:** page 18 contains submission and penalty tables. Keep those as assets instead of accidentally attaching the whole page to the preceding fuel-type rule. The provisional table text still needs reviewed rows/columns before reliable searches for formats or penalties.
- **Formulas and lettered lists:** text extraction retains line runs, but does not guarantee the original mathematical structure or table-cell association. Keep the PDF accessible and review affected source regions.
- **Applicability:** GR.6.4 says rules apply to all vehicles unless otherwise specified. IC/EV restrictions also occur outside the IC/EV chapters, such as F.9, F.10, F.11, and inspection sections. Headings alone are not authoritative applicability evidence (GR.6.3). A naive chapter filter would miss relevant general or inspection rules.
- **Referenced illustrations:** GR.6.5 distinguishes illustrative guidance from figures referred to by rule text. Asset links should preserve that relationship rather than treating every drawing as an independent requirement.
- **Classification quality:** checking every unit removes shortlist exclusions, but does not guarantee recall. Jev can still misunderstand a rule or query. Its documentation specifically identifies weaknesses in precise numerical reasoning and indirect references. Use it to locate source material; leave arithmetic and limits to deterministic logic or human assessment.

## Recommendation for the next implementation step

Start with the full scan and the versioned rule schema. First review table structure and a focused set of referenced diagrams. Then label about 25–40 representative queries covering scattered requirements, synonyms, forbidden designs, exceptions, EV/IC scope, numerical limits, and questions absent from this rulebook. Evaluate the full scan against that set.

Optimize only after measurement. If full scans are too slow or become expensive at higher usage, add BM25 plus embeddings for a generous shortlist and retain the full scan as a comparison/fallback. Measure shortlist recall against reviewed expected rule sets before accepting the speedup. The principal difficulty is preserving rule context and references; approximately 1,400 candidates is a manageable first corpus.
