from pydantic import BaseModel, ConfigDict

from agent.expression_generation.expression_type_validation import (
    ExpressionValidationInput, ExpressionValidationResult, MethodChainValidator, SimpleExpressionPlan,
)
from agent.expression_generation.type_system import MethodRegistry, TypeRegistry
from agent.expression_generation.typed_context import TypedExpressionContext


class SimplePlanRuntime(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    type_registry: TypeRegistry
    method_registry: MethodRegistry


class SimplePlanValidator:
    def validate_simple_plan(self, plan: SimpleExpressionPlan, typed_context: TypedExpressionContext,
                             runtime: SimplePlanRuntime) -> ExpressionValidationResult:
        return MethodChainValidator(ExpressionValidationInput(
            typed_context=typed_context, type_registry=runtime.type_registry,
            method_registry=runtime.method_registry,
        )).validate(plan)
