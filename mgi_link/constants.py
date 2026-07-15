"""MGI domain constants: field catalogues, vocabularies, citation, license.

Sourced from the MGI bulk data reports at
``https://www.informatics.jax.org/downloads/reports/`` (column layouts verified
2026-06-12) and the Mammalian Phenotype (MP) ontology. The top-level MP system
list (the gene-page "Phenotype Overview" grid) is derived dynamically from the
MP ontology at build time (direct children of ``MP:0000001``), so no fragile
hardcoded MP ids are needed here.
"""

from __future__ import annotations

#: Bumped when the SQLite schema or build logic changes incompatibly.
SCHEMA_VERSION = 1

#: NCBI taxon id for Mus musculus (laboratory mouse).
MOUSE_TAXON_ID = "10090"
HUMAN_TAXON_ID = "9606"

#: Root MP term ("mammalian phenotype"); its direct children are the top systems.
MP_ROOT = "MP:0000001"

#: Scalar marker fields kept as columns on the ``marker`` table.
MARKER_SCALAR_FIELDS: tuple[str, ...] = (
    "mgi_id",
    "symbol",
    "name",
    "marker_type",
    "feature_type",
    "chromosome",
    "cm_position",
    "coord_start",
    "coord_end",
    "strand",
    "status",
    "entrez_id",
    "ensembl_gene_id",
    "refseq_id",
)

#: MGI marker types (the ``Marker Type`` column of MRK_List2.rpt).
MARKER_TYPES: tuple[str, ...] = (
    "Gene",
    "Pseudogene",
    "DNA Segment",
    "QTL",
    "Cytogenetic Marker",
    "BAC/YAC end",
    "Complex/Cluster/Region",
    "Transgene",
    "Other Genome Feature",
    "GeneModel",
)

#: Allele "generation method" categories (the ``Allele Type`` column of
#: MGI_PhenotypicAllele.rpt) — these drive the gene-page allele category counts.
ALLELE_TYPES: tuple[str, ...] = (
    "Targeted",
    "Endonuclease-mediated",
    "Gene trapped",
    "Spontaneous",
    "Chemically induced (ENU)",
    "Chemically induced (other)",
    "Chemically and radiation induced",
    "Radiation induced",
    "Transgenic",
    "Transposon induced",
    "Targeted (Recombinase)",
    "QTL",
    "Not Applicable",
    "Not Specified",
    "Other",
)

#: Filter synonyms accepted for the ``allele_type`` argument (case-insensitive),
#: mapping a friendly token to a substring matched against the canonical type.
ALLELE_TYPE_ALIASES: dict[str, str] = {
    "targeted": "Targeted",
    "knockout": "Targeted",
    "ko": "Targeted",
    "crispr": "Endonuclease-mediated",
    "endonuclease": "Endonuclease-mediated",
    "endonuclease-mediated": "Endonuclease-mediated",
    "gene-trap": "Gene trapped",
    "genetrap": "Gene trapped",
    "trapped": "Gene trapped",
    "spontaneous": "Spontaneous",
    "enu": "Chemically induced (ENU)",
    "chemical": "Chemically induced",
    "chemically-induced": "Chemically induced",
    "radiation": "Radiation induced",
    "transgenic": "Transgenic",
    "transgene": "Transgenic",
    "transposon": "Transposon induced",
    "recombinase": "Targeted (Recombinase)",
    "cre": "Targeted (Recombinase)",
    "qtl": "QTL",
}

#: Ordered ortholog / cross-reference fields surfaced by get_marker_ortholog,
#: mapping the stored field name to a human-readable database label.
ORTHOLOG_XREF_FIELDS: tuple[tuple[str, str], ...] = (
    ("human_symbol", "Human Symbol"),
    ("hgnc_id", "HGNC"),
    ("human_entrez_id", "NCBI Gene (human)"),
    ("human_ensembl_id", "Ensembl (human)"),
    ("omim_gene_id", "OMIM"),
    ("human_coords", "Human Coordinates (GRCh38)"),
)

#: Reverse-lookup map for the xref index: accepted ``source`` synonym -> the
#: stored xref source key. Matched case-insensitively.
XREF_SOURCE_ALIASES: dict[str, str] = {
    "entrez_id": "entrez_id",
    "entrez": "entrez_id",
    "ncbi": "entrez_id",
    "ncbi_gene": "entrez_id",
    "ncbi_gene_id": "entrez_id",
    "gene_id": "entrez_id",
    "ensembl_gene_id": "ensembl_gene_id",
    "ensembl": "ensembl_gene_id",
    "ensmusg": "ensembl_gene_id",
    "hgnc_id": "hgnc_id",
    "hgnc": "hgnc_id",
    "omim_gene_id": "omim_gene_id",
    "omim": "omim_gene_id",
    "mim": "omim_gene_id",
    "human_symbol": "human_symbol",
    "human": "human_symbol",
}

#: Match-type provenance returned by resolve_marker.
MATCH_TYPES: tuple[str, ...] = (
    "mgi_id",
    "current",
    "synonym",
    "ortholog",
)

#: The phenotype data source (MGI_GenePheno.rpt) covers ONLY single-locus,
#: non-conditional genotypes. Conditional/Cre-driven and multi-genic genotypes are
#: excluded by MGI from this report, so a marker whose phenotypes come from such
#: genotypes (e.g. Hnf1b's renal phenotypes from Wnt4-Cre conditional alleles) can
#: report ZERO annotations here while the MGI gene page shows them. Every phenotype
#: response carries this scope so a zero/partial count is never mistaken for "this
#: gene has no such phenotype in mouse" (issue #28, defect D1).
PHENOTYPE_SCOPE = "single_locus_genotypes_only"
#: The curated, SERVER-CONTROLLED set of top-level MP system display names (the MGI
#: "Phenotype Overview" grid columns, direct children of MP:0000001). The live grid
#: is built from the downloaded MP OBO, which is EXTERNAL data; an invalid-mp_system
#: error must therefore surface only names present in this fixed allowlist, so no
#: ontology-injected label can reach the caller (issue #28 review, D2 hardening). A
#: legitimately new MGI system is still accepted at runtime (it is validated against
#: the live grid) — it is just omitted from the error list until added here.
MP_TOP_SYSTEM_NAMES: frozenset[str] = frozenset(
    {
        "adipose tissue phenotype",
        "behavior/neurological phenotype",
        "cardiovascular system phenotype",
        "cellular phenotype",
        "craniofacial phenotype",
        "digestive/alimentary phenotype",
        "embryo phenotype",
        "endocrine/exocrine gland phenotype",
        "growth/size/body region phenotype",
        "hearing/vestibular/ear phenotype",
        "hematopoietic system phenotype",
        "homeostasis/metabolism phenotype",
        "immune system phenotype",
        "integument phenotype",
        "limbs/digits/tail phenotype",
        "liver/biliary system phenotype",
        "mortality/aging",
        "muscle phenotype",
        "neoplasm",
        "nervous system phenotype",
        "normal phenotype",
        "pigmentation phenotype",
        "renal/urinary system phenotype",
        "reproductive system phenotype",
        "respiratory system phenotype",
        "skeleton phenotype",
        "taste/olfaction phenotype",
        "vision/eye phenotype",
    }
)
PHENOTYPE_SCOPE_NOTE = (
    "Phenotype annotations cover single-locus, non-conditional genotypes only "
    "(MGI_GenePheno). Conditional/Cre-driven and multi-genic genotypes are excluded "
    "by this MGI data source and may appear on the MGI gene page (e.g. tissue-specific "
    "renal phenotypes from Cre conditional alleles). A zero or partial count here does "
    "NOT mean the gene lacks that phenotype in mouse; confirm on the MGI gene page."
)

#: Zygosity codes seen in MouseMine genotype annotations.
ZYGOSITY_LABELS: dict[str, str] = {
    "hm": "homozygous",
    "ht": "heterozygous",
    "cn": "conditional",
    "cx": "complex",
    "tg": "transgenic / not applicable",
}

RECOMMENDED_CITATION = (
    "Baldarelli RM, Smith CL, Bello SM, et al. Mouse Genome Informatics: an "
    "integrated knowledgebase system for the laboratory mouse. Genetics. "
    "2024;227(1):iyae031. doi:10.1093/genetics/iyae031. RRID:SCR_006460. "
    "Data: Mouse Genome Database (MGD), The Jackson Laboratory, "
    "https://www.informatics.jax.org/."
)

#: MGI data usage. MGI data are freely available for research; the Mammalian
#: Phenotype Ontology is distributed CC BY 4.0.
MGI_LICENSE = (
    "MGI data are freely available for research use; please cite MGI / The "
    "Jackson Laboratory (see https://www.informatics.jax.org/mgihome/other/"
    "copyright.shtml). The Mammalian Phenotype Ontology is licensed CC BY 4.0."
)
