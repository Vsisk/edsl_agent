import unittest

from agent.environment.resource_filter import ResourceFilterTargetGenerator
from agent.resource_manager.loader.registry_models import DomainRegistry, SourceType


class FakeSettings:
    def model_for(self, llm_name: str) -> str:
        return f"{llm_name}-model"


class FakeClient:
    is_usable = True

    def __init__(self, content: str):
        self.content = content
        self.calls = []
        self.settings = FakeSettings()

    def complete(self, **payload):
        self.calls.append(payload)
        return self.content


class ResourceFilterTargetGeneratorTest(unittest.TestCase):
    def test_generates_context_targets_from_expression_spec_nl(self):
        client = FakeClient(
            """
            [
              {"source_type":"context","domain":"billStatement","source_name":"flowType"},
              {"source_type":"context","domain":"billStatement","source_name":"currentBillRun"},
              {"source_type":"context","domain":"billStatement","source_name":"chargeClose"},
              {"source_type":"context","domain":"curBbBillBalance","source_name":"chargeClose"}
            ]
            """
        )
        generator = ResourceFilterTargetGenerator(client=client)

        targets = generator.generate(
            query=(
                "若上下文 billStatement 的 flowType 等于 3 且 currentBillRun 等于 '1'，"
                "则取 billStatement 的 chargeClose，否则取 curBbBillBalance 的 chargeClose。"
            ),
            domain_registry=DomainRegistry(
                ctx_domains=["billStatement", "curBbBillBalance"],
            ),
        )

        self.assertEqual(
            [(target.source_type, target.domain, target.source_name) for target in targets],
            [
                (SourceType.CONTEXT, "billStatement", "flowType"),
                (SourceType.CONTEXT, "billStatement", "currentBillRun"),
                (SourceType.CONTEXT, "billStatement", "chargeClose"),
                (SourceType.CONTEXT, "curBbBillBalance", "chargeClose"),
            ],
        )
        self.assertIn("billStatement", client.calls[0]["prompt"])

    def test_drops_invalid_targets_and_records_trace(self):
        client = FakeClient(
            """
            [
              {"source_type":"context","domain":"missing","source_name":"flowType"},
              {"source_type":"bo","domain":"BB_PREP_SUB","source_name":""},
              {"source_type":"function","domain":"FuncClass","source_name":"doIt","confidence":0.5,"is_required":false}
            ]
            """
        )
        generator = ResourceFilterTargetGenerator(client=client)

        targets = generator.generate(
            query="use function",
            domain_registry=DomainRegistry(
                ctx_domains=["billStatement"],
                bo_domains=["BB_PREP_SUB"],
                func_domains=["FuncClass"],
            ),
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].source_type, SourceType.FUNCTION)
        self.assertEqual(targets[0].confidence, 0.5)
        self.assertFalse(targets[0].is_required)
        self.assertEqual(len(generator.selection_trace), 2)

    def test_parse_failure_returns_empty_targets_and_filter_target_empty_trace(self):
        generator = ResourceFilterTargetGenerator(client=FakeClient("not json"))

        targets = generator.generate(
            query="anything",
            domain_registry=DomainRegistry(ctx_domains=["billStatement"]),
        )

        self.assertEqual(targets, [])
        self.assertEqual(generator.selection_trace[-1]["reason"], "FILTER_TARGET_EMPTY")


if __name__ == "__main__":
    unittest.main()
