import csv

import click

from . import check_rank


@click.group("check")
def cli_check():
    pass


@cli_check.command("rank")
@click.argument("psa_file", type=click.File("r"))
@click.argument("ranking_file", type=click.File("r"))
def cli_check_rank(psa_file, ranking_file):
    psa_rows = list(csv.reader(psa_file))
    ranking = ranking_file.read().splitlines()
    for a, b in check_rank.check_rank(psa_rows, ranking):
        click.echo(
            f"Product {b} appears in PSA when higher-ranking product {a} does not",
            err=True,
        )


if __name__ == "__main__":
    cli_check.main()
