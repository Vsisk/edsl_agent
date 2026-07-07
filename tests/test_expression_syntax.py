import pytest

from agent.expression_generation.expression_syntax import (
    MethodChainParser,
    split_top_level_dot_chain,
)


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("charge.CHARGE_AMT.long2str()", ["charge", "CHARGE_AMT", "long2str()"]),
        ("charges.find{it.CHARGE_AMT > 0}.CHARGE_AMT", ["charges", "find{it.CHARGE_AMT > 0}", "CHARGE_AMT"]),
        ("$ctx$.address.addr1", ["$ctx$", "address", "addr1"]),
        ('dateValue("yyyy.MM.dd").addDays(1)', ['dateValue("yyyy.MM.dd")', "addDays(1)"]),
        ("fn($ctx$.a.b).length()", ["fn($ctx$.a.b)", "length()"]),
        ("1.23", ["1.23"]),
    ],
)
def test_split_top_level_dot_chain(expr, expected):
    assert split_top_level_dot_chain(expr) == expected


def test_method_chain_parser_classifies_tokens_and_arguments():
    tokens = MethodChainParser().parse('charges.find{it.CHARGE_AMT > 0}.replace("a,b", "c")')

    assert [token.token_type for token in tokens] == [
        "root", "lambda_method_call", "method_call"
    ]
    assert tokens[1].name == "find"
    assert tokens[1].lambda_expr == "it.CHARGE_AMT > 0"
    assert tokens[2].args == ['"a,b"', '"c"']
