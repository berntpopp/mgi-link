"""Command-line interface for building and refreshing the MGI index.

Exposed as the ``mgi-link-data`` console script and intended as the cron entry
point. Commands: ``build`` (force a download + rebuild), ``refresh`` (conditional
rebuild — the cron job), and ``status`` (print provenance of the existing DB).
"""

from __future__ import annotations

import typer

from mgi_link.config import get_data_config
from mgi_link.exceptions import DownloadError
from mgi_link.ingest.builder import BuildMeta, build_database, read_meta, rebuild
from mgi_link.ingest.downloader import download_bulk

app = typer.Typer(
    add_completion=False,
    help="Build and refresh the local MGI SQLite index from the bulk reports.",
)


def _print_summary(meta: BuildMeta, *, header: str) -> None:
    """Print a compact provenance summary for a build."""
    print(header)
    print(f"  schema_version  : {meta.schema_version}")
    print(f"  release         : {meta.release}")
    print(f"  markers         : {meta.marker_count}")
    print(f"  alleles         : {meta.allele_count}")
    print(f"  genopheno rows  : {meta.genopheno_count}")
    print(f"  mp terms        : {meta.mp_term_count}")
    print(f"  orthologs       : {meta.ortholog_count}")
    print(f"  disease models  : {meta.disease_count}")
    print(f"  built_utc       : {meta.build_utc}")
    if meta.build_duration_s is not None:
        print(f"  build_seconds   : {meta.build_duration_s}")


@app.command()
def build() -> None:
    """Force a download and full rebuild of the database."""
    config = get_data_config()
    try:
        download = download_bulk(config, force=True)
    except DownloadError as exc:
        print(f"ERROR: download failed: {exc}")
        raise typer.Exit(code=1) from exc
    paths = {key: download.path(key) for key in download.results}
    meta = build_database(config, paths=paths, validators=download.validators())
    _print_summary(meta, header="Built MGI database:")


@app.command()
def refresh() -> None:
    """Conditionally refresh the database; rebuild only if the reports changed."""
    config = get_data_config()
    try:
        result = rebuild(config, force=False)
    except DownloadError as exc:
        print(f"ERROR: download failed: {exc}")
        raise typer.Exit(code=1) from exc
    if result.not_modified:
        print(f"MGI database is up to date (reports not modified; release {result.meta.release}).")
        return
    _print_summary(result.meta, header="MGI database refreshed:")


@app.command()
def status() -> None:
    """Print provenance of the existing database, or a hint to build it."""
    config = get_data_config()
    meta = read_meta(config.db_path)
    if meta is None:
        print(f"No MGI database at {config.db_path}.")
        print("Run `mgi-link-data build` to download and build it.")
        raise typer.Exit(code=1)
    _print_summary(meta, header=f"MGI database at {config.db_path}:")


def main() -> None:
    """Console-script entry point for ``mgi-link-data``."""
    app()


if __name__ == "__main__":
    main()
