from orchestra.interviewer.accelerator import parse_accelerator


class TestParseAccelerator:
    def test_bracket_pattern(self):
        key, label = parse_accelerator("[A] Approve")
        assert key == "A"
        assert label == "Approve"

    def test_paren_pattern(self):
        key, label = parse_accelerator("Y) Yes, deploy")
        assert key == "Y"
        assert label == "Yes, deploy"

    def test_dash_pattern(self):
        key, label = parse_accelerator("Y - Yes, deploy")
        assert key == "Y"
        assert label == "Yes, deploy"

    def test_first_char_fallback(self):
        key, label = parse_accelerator("Fix issues")
        assert key == "F"
        assert label == "Fix issues"

    def test_empty_label(self):
        key, label = parse_accelerator("")
        assert key == ""
        assert label == ""

    def test_whitespace_only(self):
        key, label = parse_accelerator("   ")
        assert key == ""
        assert label == ""

    def test_key_uppercased(self):
        key, label = parse_accelerator("[a] approve")
        assert key == "A"
        assert label == "approve"

    def test_bracket_with_extra_whitespace(self):
        key, label = parse_accelerator("  [C] Continue  ")
        assert key == "C"
        assert label == "Continue"
