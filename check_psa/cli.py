import csv
import sys

import click

from check_psa.check_sequence import check_sequence
from check_psa.parse_psa import PsaParser


@click.command("check")
@click.option(
    "--subject",
    type=click.File("r"),
    callback=lambda ctx, param, f: PsaParser(psa_content=f.read()),
)
@click.option(
    "--reference",
    type=click.File("r"),
    callback=lambda ctx, param, f: PsaParser(psa_content=f.read()),
)
@click.option("--pm", "--product-master", type=click.File("r"), help="PM file as csv")
@click.option(
    "--filter",
    "filters",
    type=(str, str),
    multiple=True,
    help="filter PM by <col>=<value>",
)
def cli_check(subject: PsaParser, reference: PsaParser, pm, filters):
    pm_content = {}
    if pm:
        pm_headers, *pm_rows = csv.reader(pm)
        records = [dict(zip(pm_headers, row)) for row in pm_rows]
        try:
            filtered_records = [
                record
                for record in records
                if all(record[col] == val for col, val in filters)
            ]
            pm_content = {record["product_code"]: record for record in filtered_records}
        except KeyError as exc:
            click.echo(f"Could not find column {exc} in PM file", err=True)
            sys.exit(1)

    if subject and reference:
        violations = check_sequence(subject, reference, product_master=pm_content)
        for violation in violations:
            click.echo(violation)


if __name__ == "__main__":
    cli_check.main()
