"""Allow running slothd as a module: python -m slothd."""

from slothd.cli import cli

if __name__ == "__main__":
    cli()
