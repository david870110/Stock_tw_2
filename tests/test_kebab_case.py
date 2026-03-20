from src.utils.kebab_case import is_kebab_case, to_kebab_case


def test_to_kebab_case_examples():
    assert to_kebab_case("Fail Route Check") == "fail-route-check"
    assert to_kebab_case("  retry_path  validation  ") == "retry-path-validation"
    assert to_kebab_case("already-kebab-case") == "already-kebab-case"


def test_is_kebab_case_examples():
    assert is_kebab_case("a") is True
    assert is_kebab_case("fail-route-check") is True
    assert is_kebab_case("v2-api") is True
    assert is_kebab_case("123") is True

    assert is_kebab_case("") is False
    assert is_kebab_case(" fail-route-check") is False
    assert is_kebab_case("fail-route-check ") is False
    assert is_kebab_case("Fail-route-check") is False
    assert is_kebab_case("fail_route_check") is False
    assert is_kebab_case("fail--route") is False
    assert is_kebab_case("-fail-route") is False
    assert is_kebab_case("fail-route-") is False
    assert is_kebab_case("fáil-route") is False
    assert is_kebab_case("fail-route!") is False