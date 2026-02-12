from orchestra.backends.write_tracker import WriteTracker, modifies_files


class TestWriteTracker:
    def test_record_and_flush(self):
        tracker = WriteTracker()
        tracker.record("a.py")
        assert tracker.flush() == ["a.py"]

    def test_flush_resets(self):
        tracker = WriteTracker()
        tracker.record("a.py")
        tracker.flush()
        assert tracker.flush() == []

    def test_deduplication(self):
        tracker = WriteTracker()
        tracker.record("a.py")
        tracker.record("a.py")
        assert tracker.flush() == ["a.py"]

    def test_multiple_files_in_order(self):
        tracker = WriteTracker()
        tracker.record("a.py")
        tracker.record("b.py")
        tracker.record("c.py")
        assert tracker.flush() == ["a.py", "b.py", "c.py"]

    def test_dedup_preserves_first_seen_order(self):
        tracker = WriteTracker()
        tracker.record("b.py")
        tracker.record("a.py")
        tracker.record("b.py")
        assert tracker.flush() == ["b.py", "a.py"]


class TestModifiesFilesDecorator:
    def test_single_path_recorded(self):
        tracker = WriteTracker()

        @modifies_files
        def write_file(path: str) -> str:
            return path

        write_file("out.txt", write_tracker=tracker)
        assert tracker.flush() == ["out.txt"]

    def test_multiple_paths_recorded(self):
        tracker = WriteTracker()

        @modifies_files
        def write_files() -> list[str]:
            return ["a.py", "b.py"]

        write_files(write_tracker=tracker)
        assert tracker.flush() == ["a.py", "b.py"]

    def test_no_tracker_no_error(self):
        @modifies_files
        def write_file(path: str) -> str:
            return path

        result = write_file("out.txt")
        assert result == "out.txt"

    def test_return_value_preserved(self):
        tracker = WriteTracker()

        @modifies_files
        def write_file(path: str) -> str:
            return path

        result = write_file("out.txt", write_tracker=tracker)
        assert result == "out.txt"
