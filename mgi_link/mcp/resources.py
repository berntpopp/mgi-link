"""Static string resources for MCP instructions and discovery resources."""

from __future__ import annotations

from mgi_link.constants import MGI_LICENSE

RESEARCH_USE_NOTICE = (
    "Research use only; not for clinical decision support, diagnosis, "
    "treatment, or patient management."
)

MGI_SERVER_INSTRUCTIONS = (
    "MGI-Link grounds mouse-genetics work in Mouse Genome Informatics "
    "(informatics.jax.org). It is backed by a local index built from the MGI "
    "bulk data reports and refreshed by cron, so lookups are fast and offline. "
    "It reproduces an MGI gene/marker page — especially Mutations, Alleles, and "
    "Phenotypes.\n"
    "- Resolve first: resolve_marker(query=) maps a mouse symbol (current or "
    "synonym), an MGI id (MGI:98968 or 98968), OR a human gene symbol / HGNC id "
    "(via the mouse ortholog) to the canonical {mgi_id, symbol, match_type}. An "
    "ambiguous symbol returns an ambiguous_query error with candidates.\n"
    "- Record: get_marker(query=) returns the marker with location, xrefs, human "
    "ortholog, and summary counts. search_markers(query=) is FTS over "
    "symbol/name/synonyms.\n"
    "- Mutations & Alleles: get_marker_alleles(query=, allele_type=) returns the "
    "alleles plus generation-method category counts (Targeted, "
    "Endonuclease-mediated, Radiation induced, Chemically induced, ...).\n"
    "- Phenotypes: get_marker_phenotypes(query=, mp_system=) returns MP "
    "annotations with allelic composition, genetic background, and PubMed, plus a "
    "phenotype summary. get_phenotype_overview(query=) returns the 27-system grid "
    "(the page's Phenotype Overview). find_markers_by_phenotype(mp_id=) is the "
    "reverse lookup.\n"
    "- Cross-species: get_marker_ortholog(query=) gives the mouse<->human ortholog "
    "(HGNC/Entrez/Ensembl/OMIM); get_marker_diseases(query=) lists human-mouse "
    "disease models (DO/OMIM). Ontology: get_mp_term(mp_id=) and "
    "search_phenotype_terms(query=).\n"
    "- Verbosity: most tools take response_mode (minimal | compact | standard | "
    "full, default compact). get_marker_phenotypes returns deduplicated DISTINCT "
    "terms by default (response_mode=full for per-genotype rows).\n"
    "- Completeness: every list tool returns {total, returned, limit, truncated}; "
    "when truncated is true, follow the widen step in _meta.next_commands — never "
    "infer completeness from list length.\n"
    "- Chaining: every response carries _meta.next_commands, a ready-to-call list "
    "of {tool, arguments} steps, on success AND error. Discovery: "
    "get_server_capabilities or get_diagnostics, or read mgi://capabilities / "
    "mgi://tools. "
    f"{RESEARCH_USE_NOTICE}"
)

MGI_USAGE_NOTES = (
    "Start with resolve_marker to normalise any mouse symbol/MGI id (or human "
    "ortholog) to its canonical marker, then get_marker for the record. For the "
    "gene-page surface: get_marker_alleles (Mutations & Alleles + category "
    "counts), get_marker_phenotypes (MP annotations + summary), "
    "get_phenotype_overview (the system grid), get_marker_diseases and "
    "get_marker_ortholog (cross-species). Reverse research: "
    "find_markers_by_phenotype(mp_id=) returns every mouse gene annotated with an "
    "MP term (descendants included by default). Follow _meta.next_commands to "
    "advance without guessing the next tool."
)

MGI_REFERENCE_NOTES = (
    "Error codes: invalid_input, not_found, ambiguous_query, upstream_unavailable, "
    "rate_limited, internal. match_type on "
    "resolve_marker is mgi_id | current | synonym | ortholog (ortholog = resolved "
    "from a human gene). The local index is built from the MGI bulk reports "
    "(MRK_List2, MGI_PhenotypicAllele, MGI_GenePheno, VOC_MammalianPhenotype, "
    "MPheno_OBO, HOM_MouseHumanSequence, MGI_DO) and refreshed by an external "
    "cron job; get_diagnostics reports the loaded release and counts. "
    "Phenotype annotations are single-gene genotypes (MGI_GenePheno); multigenic "
    "genotypes, IMSR strain availability, and gene expression are out of scope in "
    "v1. Truncation contract: every list tool returns total/returned/limit/truncated "
    "and a widen next_command when capped — never infer completeness from list "
    "length. Allele-count glossary: alleles_total (get_marker) and total_alleles "
    "(get_marker_alleles) are all phenotypic alleles; phenotyped_alleles (phenotype "
    f"summary) is the subset appearing in MP annotations. {MGI_LICENSE}"
)
