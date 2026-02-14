import typer

from orchestra.cli.cleanup import cleanup as cleanup_command
from orchestra.cli.compile import compile as compile_command
from orchestra.cli.doctor import doctor as doctor_command
from orchestra.cli.replay_cmd import replay as replay_command
from orchestra.cli.resume_cmd import resume as resume_command
from orchestra.cli.run import run as run_command
from orchestra.cli.status import status as status_command

app = typer.Typer(name="orchestra", help="Pipeline execution engine")
app.command(name="cleanup")(cleanup_command)
app.command(name="compile")(compile_command)
app.command(name="doctor")(doctor_command)
app.command(name="run")(run_command)
app.command(name="status")(status_command)
app.command(name="resume")(resume_command)
app.command(name="replay")(replay_command)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


if __name__ == "__main__":
    app()
