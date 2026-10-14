-- SQLite schema used by fsae_search.store for the versioned rule index.
PRAGMA foreign_keys = ON;

CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    competition_year INTEGER NOT NULL,
    version TEXT NOT NULL,
    published_date TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE CHECK(length(sha256) = 64),
    source_filename TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    page_count INTEGER NOT NULL CHECK(page_count > 0),
    extractor_version TEXT NOT NULL,
    review_status TEXT NOT NULL
);

CREATE TABLE categories (
    document_id TEXT NOT NULL REFERENCES documents,
    category_id TEXT NOT NULL,
    title TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    PRIMARY KEY(document_id, category_id)
);

CREATE TABLE rules (
    document_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    category_id TEXT NOT NULL,
    parent_rule_id TEXT, -- Nearest actual numbered ancestor; NULL at article level.
    numbered_parent_id TEXT, -- Preserve absent D.8.1 without inventing its text.
    kind TEXT NOT NULL CHECK(kind IN ('article', 'section', 'paragraph')),
    ordinal INTEGER NOT NULL,
    title TEXT, -- NULL when the PDF supplies no distinct heading.
    own_text TEXT NOT NULL, -- Excludes descendants; retain modal verbs and units.
    review_status TEXT NOT NULL,
    PRIMARY KEY(document_id, rule_id),
    FOREIGN KEY(document_id, category_id) REFERENCES categories,
    FOREIGN KEY(document_id, parent_rule_id) REFERENCES rules DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE source_spans (
    span_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents,
    rule_id TEXT,
    page_number INTEGER NOT NULL CHECK(page_number > 0), -- 1-based PDF page.
    printed_page_label TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    x0 REAL NOT NULL,
    y0 REAL NOT NULL,
    x1 REAL NOT NULL,
    y1 REAL NOT NULL,
    page_width REAL NOT NULL,
    page_height REAL NOT NULL,
    span_kind TEXT NOT NULL CHECK(span_kind IN ('text', 'source_region')),
    verbatim_text TEXT,
    CHECK(x1 >= x0 AND y1 >= y0), -- PDF points, top-left origin.
    FOREIGN KEY(document_id, rule_id) REFERENCES rules
);

CREATE TABLE assets (
    asset_id TEXT NOT NULL,
    document_id TEXT NOT NULL REFERENCES documents,
    kind TEXT NOT NULL CHECK(kind IN ('table', 'figure', 'formula')),
    title TEXT,
    source_span_id TEXT NOT NULL REFERENCES source_spans,
    extracted_text TEXT,
    structured_data_json TEXT, -- Reviewed table cells, units, diagram dimensions.
    transcription_status TEXT NOT NULL,
    PRIMARY KEY(document_id, asset_id)
);

CREATE TABLE rule_assets (
    document_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    relation TEXT NOT NULL CHECK(relation IN ('refers_to', 'contains', 'illustrates')),
    normative_status TEXT NOT NULL CHECK(normative_status IN ('referenced', 'guidance', 'unreviewed')),
    PRIMARY KEY(document_id, rule_id, asset_id),
    FOREIGN KEY(document_id, rule_id) REFERENCES rules,
    FOREIGN KEY(document_id, asset_id) REFERENCES assets
);

CREATE TABLE cross_references (
    reference_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    source_rule_id TEXT,
    source_asset_id TEXT,
    target_document_id TEXT,
    target_rule_id TEXT,
    target_asset_id TEXT,
    target_subclause TEXT, -- E.g. b in T.2.8.3.b; retain the enclosing rule too.
    literal TEXT NOT NULL,
    text_offset INTEGER,
    extraction_method TEXT NOT NULL,
    review_status TEXT NOT NULL,
    CHECK((source_rule_id IS NOT NULL) <> (source_asset_id IS NOT NULL)),
    FOREIGN KEY(document_id, source_rule_id) REFERENCES rules,
    FOREIGN KEY(document_id, source_asset_id) REFERENCES assets
    -- Target may be an external supplement or unresolved reference; no target FK.
);
CREATE INDEX references_to ON cross_references(target_document_id, target_rule_id);

CREATE TABLE rule_annotations (
    document_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    annotation_type TEXT NOT NULL, -- applicability, definition, obligation, topic.
    value_json TEXT NOT NULL,
    evidence_span_id TEXT REFERENCES source_spans,
    provenance TEXT NOT NULL, -- explicit_text / inherited_context / human_review.
    review_status TEXT NOT NULL, -- Only reviewed applicability enables hard filters.
    PRIMARY KEY(document_id, rule_id, annotation_type),
    FOREIGN KEY(document_id, rule_id) REFERENCES rules
);

CREATE TABLE search_units (
    unit_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    rule_id TEXT,
    asset_id TEXT,
    role TEXT NOT NULL CHECK(role IN ('leaf', 'parent_introduction', 'asset')),
    candidate_json TEXT NOT NULL, -- Own text, headings, ancestor introduction text.
    content_sha256 TEXT NOT NULL,
    context_builder_version TEXT NOT NULL,
    CHECK((rule_id IS NOT NULL) <> (asset_id IS NOT NULL)),
    FOREIGN KEY(document_id, rule_id) REFERENCES rules,
    FOREIGN KEY(document_id, asset_id) REFERENCES assets
);

CREATE TABLE search_runs (
    run_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents,
    query TEXT NOT NULL,
    model_requested TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    threshold REAL,
    settings_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    complete INTEGER NOT NULL CHECK(complete IN (0, 1))
);

CREATE TABLE search_decisions (
    run_id TEXT NOT NULL REFERENCES search_runs,
    unit_id TEXT NOT NULL REFERENCES search_units,
    model_resolved TEXT,
    status TEXT NOT NULL CHECK(status IN ('scored', 'error')),
    relevance_probability REAL CHECK(relevance_probability BETWEEN 0 AND 1),
    PRIMARY KEY(run_id, unit_id),
    CHECK((status = 'scored' AND relevance_probability IS NOT NULL) OR
          (status = 'error' AND relevance_probability IS NULL))
);
