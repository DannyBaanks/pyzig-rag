from pyzig.fuzz.triage import pred_parseint_precedencia_overflow


def test_prefijo_de_mas_de_4300_digitos_no_revienta():
    ctx = {"input": {"text": "9" * 5000 + "+", "base": "10"},
           "oracle": {"status": "err", "error": "InvalidLiteral"}}
    assert pred_parseint_precedencia_overflow(ctx) is True
