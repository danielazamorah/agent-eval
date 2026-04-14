"""agent-eval CLI — evaluate your ADK agents with confidence."""

import importlib.metadata
import sys

import click
from rich.console import Console
from rich.panel import Panel

console = Console()


def _get_version() -> str:
    try:
        return importlib.metadata.version("agent-eval")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def _display_banner() -> None:
    version = _get_version()
    panel = Panel(
        "Evaluate your ADK agents with confidence.",
        title=f"agent-eval v{version}",
        border_style="blue",
        padding=(0, 2),
    )
    console.print(panel)


def print_version(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    console.print(f"agent-eval v{_get_version()}")
    ctx.exit()


@click.group(help="Evaluation CLI for ADK agents.")
@click.option(
    "--version", "-v",
    is_flag=True,
    callback=print_version,
    expose_value=False,
    is_eager=True,
    help="Show version and exit.",
)
def cli() -> None:
    pass


# --- Register commands ---

from agent_eval.cli.commands.interact import interact  # noqa: E402
from agent_eval.cli.commands.evaluate import evaluate  # noqa: E402
from agent_eval.cli.commands.analyze import analyze  # noqa: E402
from agent_eval.cli.commands.convert import convert  # noqa: E402
from agent_eval.cli.commands.create_dataset import create_dataset  # noqa: E402
from agent_eval.cli.commands.init import init  # noqa: E402
from agent_eval.cli.commands.simulate import simulate  # noqa: E402
from agent_eval.cli.commands.run import run  # noqa: E402
from agent_eval.cli.commands.dashboard import dashboard  # noqa: E402

cli.add_command(interact)
cli.add_command(evaluate)
cli.add_command(analyze)
cli.add_command(convert)
cli.add_command(create_dataset, name="create-dataset")
cli.add_command(init)
cli.add_command(simulate)
cli.add_command(run)
cli.add_command(dashboard)


def main():
    """Entry point for the agent-eval CLI (used by pyproject.toml scripts)."""
    cli()


if __name__ == "__main__":
    main()
