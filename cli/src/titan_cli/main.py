"""Entry point of the titan command."""

import argparse
from importlib.metadata import version


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run the command it names."""
    parser = argparse.ArgumentParser(
        prog="titan", description="TITAN from the command line."
    )
    parser.add_argument("--version", action="version", version=version("titan-cli"))
    parser.parse_args(argv)
