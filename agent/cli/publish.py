"""CLI: publish commands — package and distribute tools."""

from pathlib import Path

import click


@click.group(name="publish")
def publish():
    """Package and publish tools/roles/dont-do.

    Examples:
      therain2020-agent publish init my-tool
      therain2020-agent publish build
      therain2020-agent publish verify
    """
    pass


@publish.command()
@click.argument("name")
@click.option("--type", "-t", "pkg_type", default="tool",
              type=click.Choice(["tool", "role", "dont-do"]))
def init(name: str, pkg_type: str):
    """Initialize a new package directory."""
    from agent.publish import init_package

    pkg_dir = init_package(name, package_type=pkg_type)
    click.echo(f"Created {pkg_dir}/")
    click.echo(f"  {pkg_dir}/therain2020-package.yaml")
    click.echo(f"  {pkg_dir}/{pkg_type.rstrip('s')}.md")
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Edit the package.yaml with your info")
    click.echo(f"  2. Write your {pkg_type} description in {pkg_type.rstrip('s')}.md")
    click.echo("  3. Run: therain2020-agent publish build")
    click.echo("  4. Run: therain2020-agent publish --to github")


@publish.command()
@click.option("--dir", "-d", default=".", help="Package directory")
def build(dir: str):
    """Build a .tar.gz package."""
    from agent.publish import build_package

    pkg_dir = Path(dir)
    try:
        archive = build_package(pkg_dir)
        click.echo(f"Built: {archive}")
        click.echo()
        click.echo("To publish to GitHub:")
        click.echo(f"  1. git tag v$(grep version {pkg_dir}/therain2020-package.yaml | head -1 | cut -d'\"' -f2)")
        click.echo("  2. git push --tags")
        click.echo("  (GitHub Actions will attach .tar.gz to Release)")
    except ValueError as e:
        click.echo(str(e), err=True)


@publish.command()
@click.option("--dir", "-d", default=".", help="Package directory")
def verify(dir: str):
    """Validate a package."""
    from agent.publish import validate_package

    issues = validate_package(Path(dir))
    if not issues:
        click.echo("Package is valid.")
    else:
        click.echo("Package has issues:")
        for issue in issues:
            click.echo(f"  - {issue}")
