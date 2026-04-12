from __future__ import annotations

import click

from data_proc.candidates_pipeline import (
    build_candidates_command,
    build_candidates_eval_command,
)
from data_proc.options_pipeline import (
    build_character_bank_command,
    build_options_command,
    build_options_eval_command,
)
from data_proc.pipeline import build_quotes_command, build_quotes_eval_command
from data_proc.source_reader import build_source_reader_command


@click.group()
def cli() -> None:
    pass


cli.add_command(build_quotes_command)
cli.add_command(build_quotes_eval_command)
cli.add_command(build_candidates_command)
cli.add_command(build_candidates_eval_command)
cli.add_command(build_character_bank_command)
cli.add_command(build_options_command)
cli.add_command(build_options_eval_command)
cli.add_command(build_source_reader_command)


def main() -> None:
    cli()
