import typer

from orchestra.cli.doctor import doctor as doctor_command

app = typer.Typer(name="orchestra", help="Pipeline execution engine")
app.command()(doctor_command)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


if __name__ == "__main__":
    app()
