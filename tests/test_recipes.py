from smart_tests.recipes import primeng


def test_first_number():
    assert primeng.first_number("Mostrando 1 a 10 de 42") == 1
    assert primeng.first_number("sin número") is None


def test_row_action_selectors_cover_the_four_kinds():
    # The selector strings must mention the PrimeIcons the real app uses (mapped 2026-10-15).
    import inspect
    src = inspect.getsource(primeng.row_action)
    for icon in ("pi-plus", "pi-pencil", "pi-trash"):
        assert icon in src
    for kind in ("add", "edit", "delete", "restore"):
        assert f'"{kind}"' in src
