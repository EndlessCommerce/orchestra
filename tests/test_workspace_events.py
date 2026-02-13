from orchestra.events.dispatcher import EventDispatcher
from orchestra.events.observer import StdoutObserver
from orchestra.events.types import (
    AgentCommitCreated,
    SessionBranchCreated,
)


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list = []

    def on_event(self, event) -> None:
        self.events.append(event)


class TestSessionBranchCreated:
    def test_construction(self) -> None:
        event = SessionBranchCreated(
            repo_name="backend",
            branch_name="orchestra/pipe/abc",
            base_sha="a" * 40,
            repo_path="/workspace/backend",
        )
        assert event.repo_name == "backend"
        assert event.branch_name == "orchestra/pipe/abc"
        assert event.base_sha == "a" * 40
        assert event.repo_path == "/workspace/backend"
        assert event.event_type == "SessionBranchCreated"

    def test_dispatched_to_observer(self) -> None:
        dispatcher = EventDispatcher()
        obs = RecordingObserver()
        dispatcher.add_observer(obs)
        dispatcher.emit(
            "SessionBranchCreated",
            repo_name="project",
            branch_name="orchestra/pipe/id",
            base_sha="b" * 40,
            repo_path="/path",
        )
        assert len(obs.events) == 1
        assert isinstance(obs.events[0], SessionBranchCreated)

    def test_stdout_observer(self, capsys) -> None:
        observer = StdoutObserver()
        observer.on_event(
            SessionBranchCreated(
                repo_name="backend",
                branch_name="orchestra/pipe/abc",
                base_sha="a" * 40,
                repo_path="/workspace/backend",
            )
        )
        output = capsys.readouterr().out
        assert "Branch created" in output
        assert "orchestra/pipe/abc" in output
        assert "backend" in output


class TestAgentCommitCreated:
    def test_construction(self) -> None:
        event = AgentCommitCreated(
            repo_name="frontend",
            node_id="code",
            sha="c" * 40,
            message="feat: add login page",
            files=["src/login.tsx"],
            turn_number=1,
        )
        assert event.repo_name == "frontend"
        assert event.node_id == "code"
        assert event.sha == "c" * 40
        assert event.message == "feat: add login page"
        assert event.files == ["src/login.tsx"]
        assert event.turn_number == 1
        assert event.event_type == "AgentCommitCreated"

    def test_dispatched_to_observer(self) -> None:
        dispatcher = EventDispatcher()
        obs = RecordingObserver()
        dispatcher.add_observer(obs)
        dispatcher.emit(
            "AgentCommitCreated",
            repo_name="proj",
            node_id="code",
            sha="d" * 40,
            message="fix: bug",
            files=["a.py"],
            turn_number=2,
        )
        assert len(obs.events) == 1
        assert isinstance(obs.events[0], AgentCommitCreated)

    def test_stdout_observer(self, capsys) -> None:
        observer = StdoutObserver()
        observer.on_event(
            AgentCommitCreated(
                repo_name="proj",
                node_id="code",
                sha="abcdef1234567890" + "0" * 24,
                message="feat: add hello world\n\nAdds a simple hello.",
                files=["hello.py", "test_hello.py"],
                turn_number=1,
            )
        )
        output = capsys.readouterr().out
        assert "abcdef12" in output
        assert "feat: add hello world" in output
        assert "2 files" in output
