"""auction_pipeline CLI entry point.

Commands are registered here and implemented in the steps/ modules.
"""
from __future__ import annotations

import click

from auction_pipeline import setup_logging


@click.group()
def cli() -> None:
    """Auction Pipeline — automated due-diligence for Texas trustee sales."""
    setup_logging()


# ---------------------------------------------------------------------------
# Subcommands are imported and attached in each step module's registration
# block.  Stubs are wired below; full implementations come in later steps.
# ---------------------------------------------------------------------------

@cli.command("download")
@click.option("--month", required=True, help="Month to download, e.g. 2026-09")
@click.option("--county", default="williamson", show_default=True)
@click.option("--force", is_flag=True, default=False, help="Bypass cache and re-download")
def download_cmd(month: str, county: str, force: bool) -> None:
    """Step 0 — Download trustee-sale notices for a month."""
    from auction_pipeline.steps.step0_download import run_download
    run_download(month=month, county=county, force=force)


@cli.command("run-step")
@click.option("--step", required=True, type=int, help="Step number (1-7)")
@click.option("--month", required=True, help="Month, e.g. 2026-09")
@click.option("--county", default="williamson", show_default=True)
@click.option("--entry-no", default=None, help="Limit to a single entry number")
@click.option("--force", is_flag=True, default=False)
def run_step_cmd(step: int, month: str, county: str, entry_no: str | None, force: bool) -> None:
    """Run a single pipeline step for a month."""
    _dispatch_step(step, month=month, county=county, entry_no=entry_no, force=force)


@cli.command("run")
@click.option("--month", required=True, help="Month, e.g. 2026-09")
@click.option("--step", default="all", show_default=True,
              help="Step(s) to run: all | 0 | 1 | ... | 7")
@click.option("--county", default="williamson", show_default=True)
@click.option("--force", is_flag=True, default=False)
def run_cmd(month: str, step: str, county: str, force: bool) -> None:
    """Run all (or a specific) pipeline step(s) end-to-end."""
    from auction_pipeline.steps.step0_download import run_download

    steps_to_run: list[int]
    if step == "all":
        steps_to_run = list(range(0, 8))
    else:
        steps_to_run = [int(step)]

    for s in steps_to_run:
        if s == 0:
            run_download(month=month, county=county, force=force)
        else:
            _dispatch_step(s, month=month, county=county, entry_no=None, force=force)


@cli.command("manual-entry")
@click.option("--step", required=True, type=int)
@click.option("--entry-no", required=True)
@click.option("--status", default=None)
@click.option("--amount", default=None, type=float)
def manual_entry_cmd(step: int, entry_no: str, status: str | None, amount: float | None) -> None:
    """Record a manually-looked-up result for a step."""
    if step == 3:
        from auction_pipeline.steps.step3_tax import run_manual_entry
        run_manual_entry(entry_no=entry_no, status=status, amount=amount)
    elif step == 5:
        from auction_pipeline.steps.step5_liens import run_manual_entry as liens_manual
        liens_manual(entry_no=entry_no)
    else:
        click.echo(f"manual-entry not supported for step {step}", err=True)


@cli.command("export")
@click.option("--month", required=True)
@click.option("--output", default="out.xlsx", show_default=True)
@click.option("--county", default="williamson", show_default=True)
def export_cmd(month: str, output: str, county: str) -> None:
    """Step 7 — Export results to an Excel workbook."""
    from auction_pipeline.export.spreadsheet import run_export
    run_export(month=month, county=county, output_path=output)


# ---------------------------------------------------------------------------
# Internal dispatcher
# ---------------------------------------------------------------------------

def _dispatch_step(
    step: int,
    *,
    month: str,
    county: str,
    entry_no: str | None,
    force: bool,
) -> None:
    if step == 1:
        from auction_pipeline.steps.step1_parse_notice import run_step
        run_step(month=month, county=county, entry_no=entry_no, force=force)
    elif step == 2:
        from auction_pipeline.steps.step2_wcad import run_step
        run_step(month=month, county=county, entry_no=entry_no, force=force)
    elif step == 3:
        from auction_pipeline.steps.step3_tax import run_step
        run_step(month=month, county=county, entry_no=entry_no, force=force)
    elif step == 4:
        from auction_pipeline.steps.step4_dot import run_step
        run_step(month=month, county=county, entry_no=entry_no, force=force)
    elif step == 5:
        from auction_pipeline.steps.step5_liens import run_step
        run_step(month=month, county=county, entry_no=entry_no, force=force)
    elif step == 6:
        from auction_pipeline.steps.step6_amortize import run_step
        run_step(month=month, county=county, entry_no=entry_no, force=force)
    elif step == 7:
        from auction_pipeline.export.spreadsheet import run_export
        run_export(month=month, county=county, output_path="out.xlsx")
    else:
        click.echo(f"Unknown step: {step}", err=True)


if __name__ == "__main__":
    cli()
