-- mgi-link local index schema (built from the MGI bulk data reports).
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = OFF;

-- One row per mouse marker (MRK_List2.rpt), enriched with xrefs.
CREATE TABLE marker (
    mgi_id           TEXT PRIMARY KEY,
    symbol           TEXT NOT NULL,
    symbol_upper     TEXT NOT NULL,
    name             TEXT,
    marker_type      TEXT,
    feature_type     TEXT,
    chromosome       TEXT,
    cm_position      TEXT,
    coord_start      TEXT,
    coord_end        TEXT,
    strand           TEXT,
    status           TEXT,
    entrez_id        TEXT,
    ensembl_gene_id  TEXT,
    refseq_id        TEXT,
    synonyms         TEXT   -- JSON array of marker synonyms
);
CREATE INDEX idx_marker_symbol_upper ON marker (symbol_upper);

-- Exploded resolution index: one row per symbol form, with provenance.
CREATE TABLE marker_lookup (
    lookup_symbol  TEXT NOT NULL,   -- uppercased
    mgi_id         TEXT NOT NULL,
    symbol_type    TEXT NOT NULL    -- current | synonym
);
CREATE INDEX idx_marker_lookup ON marker_lookup (lookup_symbol);

-- Reverse cross-reference index: external id -> mgi_id.
CREATE TABLE xref (
    source       TEXT NOT NULL,     -- entrez_id | ensembl_gene_id | hgnc_id | omim_gene_id | human_symbol
    value_upper  TEXT NOT NULL,
    value        TEXT NOT NULL,
    mgi_id       TEXT NOT NULL
);
CREATE INDEX idx_xref ON xref (source, value_upper);

-- Free-text search over the searchable marker fields.
CREATE VIRTUAL TABLE marker_fts USING fts5 (
    mgi_id UNINDEXED,
    symbol,
    name,
    synonyms,
    tokenize = 'unicode61'
);

-- Phenotypic alleles / mutations (MGI_PhenotypicAllele.rpt).
CREATE TABLE allele (
    allele_id      TEXT PRIMARY KEY,
    symbol         TEXT,
    name           TEXT,
    allele_type    TEXT,            -- generation method (drives category counts)
    attributes     TEXT,            -- JSON array of allele attributes
    pubmed_ids     TEXT,            -- JSON array
    marker_id      TEXT,
    marker_symbol  TEXT
);
CREATE INDEX idx_allele_marker ON allele (marker_id);
CREATE INDEX idx_allele_type ON allele (marker_id, allele_type);

-- Gene -> phenotype annotation rows (MGI_GenePheno.rpt).
CREATE TABLE genopheno (
    marker_id            TEXT NOT NULL,
    mp_id                TEXT NOT NULL,
    allelic_composition  TEXT,
    allele_symbols       TEXT,
    allele_ids           TEXT,      -- JSON array of allele MGI ids
    genetic_background   TEXT,
    pubmed_id            TEXT,
    genotype_id          TEXT
);
CREATE INDEX idx_genopheno_marker ON genopheno (marker_id);
CREATE INDEX idx_genopheno_mp ON genopheno (mp_id);

-- Mammalian Phenotype vocabulary (VOC_MammalianPhenotype.rpt).
CREATE TABLE mp_term (
    mp_id       TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    definition  TEXT
);

-- MP free-text search.
CREATE VIRTUAL TABLE mp_fts USING fts5 (
    mp_id UNINDEXED,
    name,
    definition,
    tokenize = 'porter unicode61'
);

-- Transitive ancestor closure from the MP ontology (MPheno_OBO.ontology),
-- including the (mp_id, mp_id) self-pair, used to roll annotations up to the
-- top-level systems.
CREATE TABLE mp_closure (
    mp_id        TEXT NOT NULL,
    ancestor_id  TEXT NOT NULL
);
CREATE INDEX idx_mp_closure ON mp_closure (mp_id);
CREATE INDEX idx_mp_closure_anc ON mp_closure (ancestor_id);

-- Direct is_a parent edges from the MP ontology (for term navigation).
CREATE TABLE mp_parent (
    mp_id      TEXT NOT NULL,
    parent_id  TEXT NOT NULL
);
CREATE INDEX idx_mp_parent ON mp_parent (mp_id);
CREATE INDEX idx_mp_parent_rev ON mp_parent (parent_id);

-- Top-level MP systems (the gene-page "Phenotype Overview" grid columns):
-- the direct children of MP:0000001, derived from the ontology at build time.
CREATE TABLE mp_top_system (
    mp_id          TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    display_order  INTEGER
);

-- Mouse <-> human ortholog mapping (HOM_MouseHumanSequence.rpt).
CREATE TABLE ortholog (
    mgi_id            TEXT PRIMARY KEY,
    mouse_symbol      TEXT,
    human_symbol      TEXT,
    human_entrez_id   TEXT,
    hgnc_id           TEXT,
    omim_gene_id      TEXT,
    human_ensembl_id  TEXT,
    human_coords      TEXT
);

-- Human <-> mouse disease models (MGI_DO.rpt), mouse rows only.
CREATE TABLE disease_model (
    marker_id      TEXT NOT NULL,
    doid           TEXT,
    disease_name   TEXT,
    omim_ids       TEXT             -- JSON array
);
CREATE INDEX idx_disease_marker ON disease_model (marker_id);

-- Single-row build provenance.
CREATE TABLE meta (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version      INTEGER,
    release             TEXT,
    reports_base_url    TEXT,
    source_validators   TEXT,       -- JSON: per-report {etag, last_modified}
    marker_count        INTEGER,
    allele_count        INTEGER,
    genopheno_count     INTEGER,
    mp_term_count       INTEGER,
    ortholog_count      INTEGER,
    disease_count       INTEGER,
    build_utc           TEXT,
    build_duration_s    REAL
);
