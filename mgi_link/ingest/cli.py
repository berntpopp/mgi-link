"""Command-line interface for building and refreshing the MGI index.

Exposed as the ``mgi-link-data`` console script and intended as the cron entry
point. Commands: ``build`` (force a download + rebuild), ``refresh`` (conditional
rebuild — the cron job), and ``status`` (print provenance of the existing DB).
"""

from __future__ import annotations

import json
from email.utils import parsedate_to_datetime
from pathlib import Path

import typer

from mgi_link.config import REPORT_FILENAMES, get_data_config
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
def build(
    reproducible: bool = typer.Option(
        False,
        "--reproducible",
        help="Pin build_utc to the newest report Last-Modified so the file is byte-reproducible.",
    ),
) -> None:
    """Force a download and full rebuild of the database."""
    config = get_data_config()
    try:
        download = download_bulk(config, force=True)
    except DownloadError as exc:
        print(f"ERROR: download failed: {exc}")
        raise typer.Exit(code=1) from exc
    paths = {key: download.path(key) for key in download.results}
    validators = download.validators()
    build_utc = None
    if reproducible:
        stamps = [v["last_modified"] for v in validators.values()]
        if set(validators) != set(REPORT_FILENAMES) or not all(stamps):
            print("ERROR: --reproducible needs every report and its Last-Modified header.")
            raise typer.Exit(code=1)
        build_utc = max(parsedate_to_datetime(str(stamp)) for stamp in stamps).isoformat()
    meta = build_database(config, paths=paths, validators=validators, build_utc=build_utc)
    _print_summary(meta, header="Built MGI database:")


@app.command()
def package(
    output: Path = typer.Option(..., help="New directory for the release assets."),
    revision: str = typer.Option(..., help="Full commit SHA of the transformation code."),
    authorization: Path = typer.Option(
        Path("release/data-authorization.json"), help="Owner redistribution authorization."
    ),
) -> None:
    """Package the reproducibly built database as data-release assets; print the manifest."""
    from mgi_link.ingest.release import package_release

    config = get_data_config()
    manifest = package_release(
        config.db_path,
        reports={key: config.data_dir / name for key, name in REPORT_FILENAMES.items()},
        authorization=authorization,
        output=output,
        revision=revision,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


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


@app.command("materialize-data")
def materialize_data() -> None:
    """Restore the pinned, digest-verified data release (init sidecar only)."""
    from mgi_link.config import settings
    from mgi_link.immutable_data import materialize_immutable_data

    selected = materialize_immutable_data(settings.immutable_data)
    print(f"Materialized MGI data release {settings.immutable_data.release_tag}: {selected}")


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
