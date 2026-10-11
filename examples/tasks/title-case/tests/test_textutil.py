from textutil import title_case


def test_basic():
    assert title_case("hello world") == "Hello World"


def test_keeps_rest_of_word():
    assert title_case("hello WORLD") == "Hello WORLD"


def test_apostrophe():
    assert title_case("don't stop") == "Don't Stop"


def test_spacing():
    assert title_case("  spaced   out ") == "  Spaced   Out "
