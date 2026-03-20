from src.utils.strings import normalize_whitespace, to_snake_case


def test_to_snake_case():
    assert to_snake_case("Hello World") == "hello_world"
    assert to_snake_case("  Multi   Space  Input  ") == "multi_space_input"
    assert to_snake_case("already-snake-case") == "already_snake_case"


def test_normalize_whitespace():
    assert normalize_whitespace("  hello   world  ") == "hello world"
    assert normalize_whitespace("line\twith\tmixed\n\nwhitespace") == "line with mixed whitespace"
    assert normalize_whitespace("already clean") == "already clean"
