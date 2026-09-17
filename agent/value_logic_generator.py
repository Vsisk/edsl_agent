from __future__ import annotations

import re
import json
import inspect
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Callable

from agent.agent_runner import generate_result_by_llm
from agent.common.enums.common_enums import ProgressStatusEnum
from agent.common.utils.agent_status import AgentStatus
from agent.common.utils.logger import Logger, LogParams
from agent.context_pack import create_context_pack_manager, ContextPackRequest, \
    ProjectContext, ResourceName, ContextPack
from agent.expression_generate_op.business_context import (
    build_business_path_context,
    build_business_path_context_direct,
    LLMBusinessScopeClassifier,
)
from agent.expression_generate_op.expression_comment_generator import generate_comments
from agent.expression_generate_op.spec_generator import ExpressionSpecGenerator
from agent.expression_generate_op.value_logic_routing import ValueLogicTarget, classify_value_logic_target
from agent.expression_generate_op.value_logic_sql import SqlBranchResolver
from agent.resource_manager.type_expander import StructuredTypeExpander
from common.utils.config_utils import BILL_CONFIG, PROJECT_ROOT
from agent.context_pack.models import ContextWarning, ContextTraceItem
from agent.expression_generate_op.edsl_expression_parser import EDSLExpressionParser
from agent.expression_generate_op.models import FilteredEnvironment
from agent.expression_generate_op.environment.target_resource_searcher import TargetResourceSearcher
from agent.expression_generate_op.ast.builder import build_ast
from agent.expression_generate_op.ast.generator import generate_expression, inject_expression_comments
from agent.expression_generate_op.ast.validator import validate_ast_with_result, AstValidationContext
from agent.expression_generate_op.models import ExpressionSpec, NodeDef, ValueLogicRequest, ValueLogicResult, \
    ValueLogicSource, TermSpecMatchResult
from agent.expression_generate_op.planner.llm_planner import LLMPlanner
from agent.expression_generate_op.spec_orchestration.orchestrator import SpecOrchestrator
from agent.expression_generate_op.spec_orchestration.search import OrchestratorResourceSearch
from agent.expression_generate_op.type_system import TypeRegistry, create_builtin_method_registry, TypeRef, \
    normalize_return_type
from agent.expression_generate_op.typed_context import TypedExpressionContextBuilder, TypedExpressionContextBuildInput, \
    TypedExpressionContext
from agent.workflow.runtime.stage import StageExecutionError
from agent.workflows.expression import (
    ExpressionExecutionEnvironment,
    ExpressionWorkflowFactory,
    ExpressionWorkflowHandler,
    ExpressionWorkflowResultAdapter,
    create_expression_capability_registries,
)
from agent.workflows.value_logic import (
    ValueLogicExecutionEnvironment,
    ValueLogicWorkflowFactory,
    ValueLogicWorkflowHandler,
)
from agent.resource_manager.resource_loader import LoadedResource, ResourceLoader
from agent.resource_manager.registry_models import BoRegistry
from agent.common.schema_manager.schema_data_class import ReturnType, TreeNodeTerm, DataTypeEnum
from common.utils.file_utils import safe_get_path
from managers.version_file_manager import VersionFileManager

DEFAULT_GENERATION_MAX_ATTEMPTS = 3
MAX_RETRY_FEEDBACK_MESSAGE_LENGTH = 2000
DEFAULT_SEARCH_LIMIT = 5

_STAGE_LABELS = {
    "spec": "规格生成",
    "resource_filter": "资源筛选",
    "planner": "计划制定",
    "pipeline": "表达式构建",
    "validation": "表达式校验",
}


class _GenerationAttemptError(Exception):
    def __init__(self, stage: str, error: Exception):
        super().__init__(str(error))
        self.stage = stage
        self.error = error


class ExecutionRouteType(Enum):
    """执行路由类型枚举"""
    FILTERED_RESOURCES_PLANNER = "filtered_resources_planner"  # 筛选资源后走planner
    OOTB_OVERRIDE = "ootb_override"  # OOTB覆盖，直接返回表达式


@dataclass(slots=True)
class ExecutionRoute:
    """执行路由结果

    路由决定spec生成后应该走哪条执行路径：
    - OOTB_OVERRIDE: 直接返回表达式（来自术语库匹配等）
    - FILTERED_RESOURCES_PLANNER: require_* 门控已移除，
      非短路口一律筛选资源后再走 planner（资源组搜索由目标 resource_types 驱动）
    """
    route_type: ExecutionRouteType
    ootb_expression: str | None = None  # OOTB覆盖时返回的表达式
    ootb_datatype: dict | None = None  # OOTB覆盖时返回的datatype


@dataclass(slots=True)
class GenerationContext:
    resources_context: LoadedResource
    node: dict[str, Any]
    parent_node: dict[str, Any] | None
    query: str
    context_pack: ContextPack
    spec: ExpressionSpec | None = None
    bo_name: str | None = None
    bo_field_list: list | None = None
    retry_feedback: dict | None = None
    target: ValueLogicTarget | None = None
    filtered_env: Optional[FilteredEnvironment] = None


class ValueLogicGenerator:
    """Deprecated legacy adapter.

    The primary execution path is Harness -> WorkflowRegistry -> WorkflowRuntime
    -> ValueLogicWorkflow. Keep this class only for legacy callers that have not
    migrated to the Harness workflow entrypoint yet.
    """

    deprecated = True

    def __init__(
        self,
        *,
        reporter_info: dict,
        resource_loader: ResourceLoader | None = None,
        llm_planner: LLMPlanner | None = None,
        generation_max_attempts: int = DEFAULT_GENERATION_MAX_ATTEMPTS,
        use_target_resource_searcher: bool = True,
    ):
        if (
            not isinstance(generation_max_attempts, int)
            or isinstance(generation_max_attempts, bool)
            or generation_max_attempts < 1
        ):
            raise ValueError("generation_max_attempts must be a positive integer")
        self.generation_max_attempts = generation_max_attempts
        self.resource_loader = resource_loader or ResourceLoader()
        self.llm_planner = llm_planner or LLMPlanner()
        self.use_target_resource_searcher = use_target_resource_searcher
        self.target_searcher = TargetResourceSearcher()
        self.typed_context_builder = TypedExpressionContextBuilder()
        self.type_registry = TypeRegistry()
        self.method_registry = create_builtin_method_registry()
        self.context_pack_manager = create_context_pack_manager()
        self.reporter = reporter_info.get("reporter")
        self.current_step = reporter_info.get("current_step")
        self.request_type = reporter_info.get("request_type")
        self._logger = Logger("ValueLogicGenerator", LogParams(to_stdout=True))
        self.orchestrator: SpecOrchestrator | None = None
        self.expression_spec_generator: ExpressionSpecGenerator = ExpressionSpecGenerator()
        self.business_scope_classifier = LLMBusinessScopeClassifier()
        self.capability_registries = create_expression_capability_registries()
        self.expression_workflow_handler = ExpressionWorkflowHandler(
            workflow_factory=ExpressionWorkflowFactory(
                spec_generator=self.expression_spec_generator,
                route_fn=self._route_execution,
                infer_expected_type_fn=self._infer_expected_type,
                target_searcher=self.target_searcher,
                typed_context_builder=self.typed_context_builder,
                merge_sql_env_fn=_merge_sql_branch_env,
                type_registry=self.type_registry,
                method_registry=self.method_registry,
                llm_planner=self.llm_planner,
                build_validation_context_fn=self._build_ast_validation_context,
                type_ref_to_return_type_fn=_type_ref_to_value_return_type,
            ),
            result_adapter=ExpressionWorkflowResultAdapter(
                result_model=ValueLogicResult,
                source_model=ValueLogicSource,
                agent_status=AgentStatus,
                return_type_model=ReturnType,
                node_display_fn=self._node_display_name,
                report_progress_fn=self._report_progress,
                logger=self._logger.logger,
            ),
        )
        self.value_logic_workflow_handler = ValueLogicWorkflowHandler(
            workflow_factory=ValueLogicWorkflowFactory(
                prepare_context_fn=self._prepare_generation_context,
                resolve_sql_fn=self._resolve_sql_branch,
                resolve_bo_field_fn=self._resolve_normal_field_logic,
                summary_fn=self._generate_summary_field_logic,
                expression_fn=self._generate_expression_by_plan,
            )
        )

    def _report_progress(self, content: str) -> None:
        """通过 reporter 向前端推送进度信息"""
        self.reporter.send_process(
            ProgressStatusEnum.ANALYSIS,
            request_type=self.request_type,
            content=content,
            step_index=self.current_step,
        )

    def _node_display_name(self, request: ValueLogicRequest) -> str:
        """获取节点展示名称，用于进度消息"""
        xml_name = request.node.get("xml_name_property", {}).get("xml_name") or ""
        return (f"{request.business_path_text}/{xml_name}"
                or xml_name
                or "").strip() or "节点"

    @staticmethod
    def _summarize_spec_result(spec_result: Any) -> str:
        """将 spec 生成结果简化为可展示的摘要"""
        if isinstance(spec_result, TermSpecMatchResult):
            return f"术语库匹配命中: {spec_result.expression}"
        if isinstance(spec_result, ExpressionSpec):
            spec_text = (spec_result.spec or "").strip()
            return spec_text[:200] + ("..." if len(spec_text) > 200 else "")
        return ""

    @staticmethod
    def _summarize_filtered_env(filtered_env: FilteredEnvironment) -> str:
        """将筛选后的资源环境简化为可展示的摘要"""
        if not filtered_env:
            return "未筛选到相关资源"
        parts: list[str] = []
        bo_names = [bo.bo_name for bo in filtered_env.selected_bos if bo.bo_name]
        if bo_names:
            parts.append(f"BO: {', '.join(bo_names)}")
        ctx_names = [c.context_name for c in filtered_env.selected_global_contexts if c.context_name]
        if ctx_names:
            parts.append(f"全局上下文: {', '.join(ctx_names)}")
        local_names = [c.context_name for c in filtered_env.visible_local_context if c.context_name]
        if local_names:
            parts.append(f"局部上下文: {', '.join(local_names)}")
        ns_names = [ns.naming_sql_name for ns in filtered_env.naming_sql_resources if ns.naming_sql_name]
        if ns_names:
            parts.append(f"NamingSQL: {', '.join(ns_names)}")
        func_names = [f.func_name for f in filtered_env.selected_functions if f.func_name]
        if func_names:
            parts.append(f"函数: {', '.join(func_names)}")
        return "；".join(parts) if parts else "未筛选到相关资源"

    @staticmethod
    def _summarize_plan(plan_result: dict) -> str:
        """将 plan 结果简化为可展示的摘要"""
        plan = plan_result.get("simple_plan")
        if plan is None:
            return ""
        if hasattr(plan, "return_expr"):
            return_expr = (plan.return_expr or "").strip()
            return return_expr[:300] + ("..." if len(return_expr) > 300 else "")
        return ""

    def generate(self, request: ValueLogicRequest) -> ValueLogicResult:
        return self.value_logic_workflow_handler.execute(
            request=request,
            environment=ValueLogicExecutionEnvironment(request=request),
        )

    def _prepare_generation_context(
        self,
        request: ValueLogicRequest,
    ) -> tuple[GenerationContext, ValueLogicTarget | None]:
        # 调用方（intent_router op）已推导 business_scope/business_path_text 时直接复用，
        # 避免重复走 build_business_path_context（含 LLM scope 分类）
        if request.business_path_text or request.business_scope:
            system_context = build_business_path_context_direct(
                node_path=request.node_path,
                business_path_text=request.business_path_text,
                business_scope=request.business_scope,
            ).model_dump(mode="json")
        else:
            system_context = build_business_path_context(
                edsl_tree=request.edsl_tree,
                node_path=request.node_path,
                current_node=request.node,
                scope_classifier=self.business_scope_classifier,
            ).model_dump(mode="json")
        target = None
        if request.is_ab or isinstance(request.node.get("tree_node_type"), str):
            target = classify_value_logic_target(request.node)
        node_name = self._node_name(request.node)
        self._logger.logger.info(f"[ValueLogicGenerator] Start generating"
                                 f" expression for node: {node_name}, is_ab={request.is_ab}")
        resources = self.resource_loader.load_resource(
                request.site_id,
                request.project_id,
                request.edsl_tree,
                is_sub_xml=request.is_sub_xml,
            )

        resource_names = ["dev_skill", "ootb_edsl", "current_tree"]
        site_level_path = BILL_CONFIG.billgen.modeling.project_path + f"/{request.site_id}/site_level"
        context_pack = self.context_pack_manager.build(
            ContextPackRequest(
                node=request.node,
                query=request.query,
                resource_names=[ResourceName(resource_name) for resource_name in resource_names],
                system_context=system_context,
            ),
            ProjectContext(
                current_tree=request.edsl_tree,
                ootb_tree=self._load_ootb_json(request.project_type),
                dev_skill_path=Path(safe_get_path(PROJECT_ROOT, site_level_path, "/skills/expression-knowledge-summary/SKILL.md")),
                loaded_resource=resources,
            ),
        )
        context_pack = context_pack.model_copy(update={
            "warnings": [*context_pack.warnings, ContextWarning(
                code="CONTEXT_RESOURCE_ROUTE_FALLBACK",
                message="all context resources enabled",
            )],
            "trace": [*context_pack.trace, ContextTraceItem(
                source="context_resource_router",
                action="fallback",
                detail="all context resources enabled",
            )],
        }, deep=True)
        ctx = GenerationContext(
            resources_context=resources,
            node=request.node,
            parent_node=request.parent_node,
            query=request.query,
            context_pack=context_pack,
            target=target,
        )
        return ctx, target

    def _generate_target_logic(
        self,
        request: ValueLogicRequest,
        ctx: GenerationContext,
        target: ValueLogicTarget,
    ) -> ValueLogicResult:
        return self.value_logic_workflow_handler.execute(
            request=request,
            environment=ValueLogicExecutionEnvironment(request=request),
        )

    def _generate_sql_branch(self, request: ValueLogicRequest, ctx: GenerationContext) -> ValueLogicResult:
        result = self._resolve_sql_branch(request, ctx)
        if result is not None:
            return result
        return self.value_logic_workflow_handler.execute(
            request=request,
            environment=ValueLogicExecutionEnvironment(request=request),
        )

    def _resolve_sql_branch(self, request: ValueLogicRequest, ctx: GenerationContext) -> ValueLogicResult | None:
        resolver = SqlBranchResolver()
        result = resolver.resolve(
            query=request.query,
            node=request.node,
            node_path=request.node_path,
            loaded_resource=ctx.resources_context,
            context_pack=ctx.context_pack,
        )
        if result is not None:
            return result
        if resolver.naming_sql_hint is not None:
            ctx.context_pack = ctx.context_pack.model_copy(update={
                "system_context": {
                    **ctx.context_pack.system_context,
                    "naming_sql_hint": resolver.naming_sql_hint,
                }
            }, deep=True)
        if resolver.filtered_env is not None:
            ctx.filtered_env = resolver.filtered_env
        return None

    def _generate_summary_field_logic(self, request: ValueLogicRequest, ctx: GenerationContext) -> ValueLogicResult:
        node_name = self._node_name(request.node)
        self._logger.logger.info(f"[ValueLogicGenerator] Generating summary field logic, node={node_name}")
        detail_fields = self._extract_detail_field(request.parent_node)
        self._logger.logger.debug(f"[ValueLogicGenerator] Detail fields: {[f['name'] for f in detail_fields]}")
        response = generate_result_by_llm(prompt_template=["InnerExpressionSum"], llm_name="base",
                                          query=request.query, node_def=request.node, detail_fields=detail_fields,
                                          verbose=False)
        self._logger.logger.debug(f"[ValueLogicGenerator] LLM response for summary: {response}")
        summary_type = self._normalize_summary_type(response.get("agg_type", ""))
        self._logger.logger.info(f"[ValueLogicGenerator] Summary type: {summary_type}")
        if summary_type == "sum":
            target_node_id = min(int(response.get("target_node_id", 0)), len(detail_fields))
            target_node_name = detail_fields[target_node_id]["name"]
            self._logger.logger.info(f"[ValueLogicGenerator] Summary field mapped to detail field: {target_node_name}")

            return ValueLogicResult(
                status=AgentStatus.SUCCESS,
                logic_type="summary",
                expression=None,
                source=ValueLogicSource(
                    source_type="detail_field",
                    detail_field=target_node_name,
                    summary_type=summary_type,
                ),
            )

        return ValueLogicResult(
            status=AgentStatus.SUCCESS,
            logic_type="summary",
            expression=None,
            source=ValueLogicSource(
                source_type="detail_field",
                summary_type=summary_type,
            ),
        )

    def _generate_normal_field_logic(self, request: ValueLogicRequest, ctx: GenerationContext) -> ValueLogicResult:
        result = self._resolve_normal_field_logic(request, ctx)
        if result is not None:
            return result
        return self.value_logic_workflow_handler.execute(
            request=request,
            environment=ValueLogicExecutionEnvironment(request=request),
        )

    def _resolve_normal_field_logic(self, request: ValueLogicRequest, ctx: GenerationContext) -> ValueLogicResult | None:
        node_name = self._node_name(request.node)
        if not request.node.get("field_id"):
            return None
        self._logger.logger.info(f"[ValueLogicGenerator] Generating normal field logic, node={node_name}")
        if not request.parent_node:
            self._logger.logger.info(f"[ValueLogicGenerator] No parent node, fallthrough to expression by plan")
            return None

        parent_node = TreeNodeTerm(**request.parent_node)
        return_type = parent_node.get_return_type()

        if not return_type:
            self._logger.logger.info(f"[ValueLogicGenerator] No BO mapping found, fallthrough to expression by plan")
            return None

        self._logger.logger.info(f"[ValueLogicGenerator] Resource mapping found: bo_name={return_type.data_type_name}")
        if return_type.data_type == "bo":
            bo_registry = ctx.resources_context.bo_registry.get(return_type.data_type_name)
            fields_list = [{"id": idx, "name": item.field_name, "desc": item.description}
                              for idx, item in enumerate(bo_registry.property_list)]
        else:
            type_expander = StructuredTypeExpander(ctx.resources_context.type_defs or [])
            fields_list = type_expander.descendants(normalize_return_type(return_type))
        self._logger.logger.debug(f"[ValueLogicGenerator] fields list: {len(fields_list)}")
        response = generate_result_by_llm(prompt_template=["InnerExpression"], llm_name="base",
                                          query=request.query, parent_node=request.parent_node,
                                          data_resource=fields_list, verbose=False)
        self._logger.logger.debug(f"[ValueLogicGenerator] LLM response for BO mapping: {response}")
        if response.get("data_source_type", "") == "expression":
            ctx.bo_field_list = fields_list
            self._logger.logger.info(f"[ValueLogicGenerator] LLM chose expression, proceeding to expression by plan")
            return None

        target_field_id = min(int(response.get("table_field_id", 0)), len(fields_list))
        target_field_name = fields_list[target_field_id]["name"]
        self._logger.logger.info(f"[ValueLogicGenerator] BO field mapping result: {target_field_name}")

        return ValueLogicResult(
            status=AgentStatus.SUCCESS,
            logic_type="bo_field_mapping",
            expression=None,
            source=ValueLogicSource(
                source_type="bo",
                bo_field=target_field_name
            )
        )

    def _generate_expression_by_plan(self, request: ValueLogicRequest, ctx: GenerationContext) -> ValueLogicResult:
        node_display = self._node_display_name(request)
        for attempt in range(1, self.generation_max_attempts + 1):
            try:
                result = self._generate_expression_attempt(request, ctx)
            except _GenerationAttemptError as failure:
                stage_label = _STAGE_LABELS.get(failure.stage, failure.stage)
                if attempt == self.generation_max_attempts:
                    self._report_progress(f"{node_display} : {stage_label}失败，表达式生成失败")
                    return ValueLogicResult(
                        status=AgentStatus.FAILED,
                        logic_type="expression",
                        expression="\"\"",
                        return_type=ReturnType().model_dump(),
                        source=ValueLogicSource(source_type="plan"),
                    )
                self._report_progress(
                    f"{node_display} : {stage_label}失败，正在重试({attempt}/{self.generation_max_attempts})...")
                ctx.retry_feedback = _build_retry_feedback(
                    attempt=attempt,
                    stage=failure.stage,
                    error_type=type(failure.error).__name__,
                    message=str(failure.error),
                )
                continue
            if result.logic_type != "validation_failed" or attempt == self.generation_max_attempts:
                return result
            self._report_progress(
                f"{node_display} : 表达式校验失败，正在重试({attempt}/{self.generation_max_attempts})...")
            error = result.validation_errors[0] if result.validation_errors else {}
            ctx.retry_feedback = _build_retry_feedback(
                attempt=attempt,
                stage="validation",
                error_type=str(error.get("error_type") or "VALIDATION_FAILED"),
                message=str(error.get("message") or "expression validation failed"),
            )

        return ValueLogicResult(
            status=AgentStatus.FAILED,
            logic_type="expression",
            expression="\"\"",
            return_type=ReturnType().model_dump(),
            source=ValueLogicSource(source_type="plan"),
        )

    def _generate_expression_attempt(
            self,
            request: ValueLogicRequest,
            ctx: GenerationContext
    ) -> ValueLogicResult:
        try:
            environment = ExpressionExecutionEnvironment(
                request=request,
                resources_context=ctx.resources_context,
                context_pack=ctx.context_pack,
                node_info=self._to_node_def(request.node, request.node_path),
                retry_feedback=ctx.retry_feedback,
                initial_filtered_env=ctx.filtered_env,
                capability_registries=self.capability_registries,
            )
            return self.expression_workflow_handler.execute(
                request=request,
                environment=environment,
            )
        except StageExecutionError as exc:
            raise _GenerationAttemptError(exc.stage, exc.error) from exc
        except _GenerationAttemptError:
            raise
        except Exception as exc:
            raise _GenerationAttemptError("pipeline", exc) from exc

    def _route_execution(self, spec_result: ExpressionSpec | TermSpecMatchResult, request: ValueLogicRequest) -> ExecutionRoute:
        """根据spec生成结果路由到后续操作

        1. 如果术语库匹配命中（TermSpecMatchResult），直接返回OOTB_OVERRIDE
        2. 否则（ExpressionSpec）一律走 FILTERED_RESOURCES_PLANNER：
           require_* 门控已移除，资源筛选依据目标 resource_types 全量搜索，
           不再区分为 DIRECT_PLANNER。
        """
        # 1) 短路口：术语库匹配直接返回
        if isinstance(spec_result, TermSpecMatchResult):
            xml_name = request.node.get("xml_name_property", {}).get("xml_name", "")
            self.reporter.send_process(
                ProgressStatusEnum.ANALYSIS,
                request_type=self.request_type,
                content=f"{xml_name}: 术语库匹配命中，直接返回表达式",
                step_index=self.current_step
            )
            return ExecutionRoute(
                route_type=ExecutionRouteType.OOTB_OVERRIDE,
                ootb_expression=spec_result.expression,
                ootb_datatype=spec_result.datatype,
            )

        # 2) 非短路口：一律走资源筛选后 planner
        return ExecutionRoute(
            route_type=ExecutionRouteType.FILTERED_RESOURCES_PLANNER,
        )

    def _to_node_def(self, node: dict[str, Any], node_path: str) -> NodeDef:
        return NodeDef(
            node_id=self._node_id(node) or "",
            node_path=node_path,
            node_name=self._node_name(node),
            description=str(node.get("annotation") or ""),
        )

    def _infer_expected_type(self, request: ValueLogicRequest) -> ReturnType:
        data_type = request.data_type or {}
        data_type_name = data_type.get("data_type_name", "")
        type_kind = data_type.get("data_type", "basic")
        is_list = data_type.get("is_list", False)
        return ReturnType(
            data_type=type_kind,
            data_type_name=data_type_name,
            is_list=is_list,
        )

    def _is_sql_source(self, parent_node: dict[str, Any]) -> bool:
        ab_content = parent_node.get("ab_content", {})
        if "data_source" in ab_content:
            data_source = ab_content["data_source"]
            if data_source["data_source_type"] == "sql":
                return True
        return False

    def _extract_detail_field(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        if not node:
            raise ValueError("The parent node cannot be empty.")

        if node.get("tree_node_type") != "ab_two_level_table":
            raise ValueError("The node type must be ab_two_level_table.")

        ab_content = node.get("ab_content", {})
        detail_region = ab_content.get("detail_region", {})
        detail_fields = detail_region.get("detail_fields", [])
        return [{
            "id": idx,
            "name": item["xml_name_property"].get("xml_name", ""),
            "desc": item["annotation"]
            } for idx, item in enumerate(detail_fields)
        ]

    def _normalize_summary_type(self, value: Any) -> str | None:
        normalized = str(value or "").strip().lower()
        if normalized in {"sum", "count"}:
            return normalized
        return None

    def _node_id(self, node: dict[str, Any]) -> str | None:
        for key in ("node_id", "id", "field_id"):
            value = node.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    def _node_name(self, node: dict[str, Any]) -> str:
        xml_name_property = node.get("xml_name_property")
        if isinstance(xml_name_property, dict):
            xml_name = xml_name_property.get("xml_name")
            if xml_name is not None and str(xml_name).strip():
                return str(xml_name).strip()
        return self._node_id(node) or ""

    def _load_ootb_json(self, project_type: str) -> dict[str, Any] | None:
        """读取并返回OOTB JSON文件内容
        """
        ootb_path = VersionFileManager.get_template_base_edsl_path(project_type)
        try:
            path = Path(ootb_path)
            if not path.is_file():
                self._logger.logger.warning(f"[ValueLogicGenerator] OOTB JSON file not found: {ootb_path}")
                return None
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            self._logger.logger.error(f"[ValueLogicGenerator] Failed to parse OOTB JSON: {ootb_path}, error: {e}")
            return None
        except Exception as e:
            self._logger.logger.error(f"[ValueLogicGenerator] Failed to read OOTB JSON: {ootb_path}, error: {e}")
            return None

    def _build_ast_validation_context(
        self,
        *,
        loaded_resource: LoadedResource,
        filtered_env,
        typed_context=None,
    ) -> AstValidationContext:
        context_registry = dict(loaded_resource.context_registry)
        context_registry.update(
            {
                context.context_name: context
                for context in getattr(filtered_env, "visible_local_context", []) or []
            }
        )
        context_types = {}
        function_types = {}
        bo_types = {
            bo_name: TypeRef(kind="bo", name=bo_name)
            for bo_name in loaded_resource.bo_registry
        }
        fetch_return_types = {}
        function_params: dict[str, int] = {}
        fetch_params: dict[str, set[str]] = {}
        for func in loaded_resource.function_registry.values():
            key = ".".join(p for p in (func.func_class, func.func_name) if p)
            function_params[key] = len(func.param_list)
        for bo in loaded_resource.bo_registry.values():
            for ns in bo.naming_sql_list:
                fetch_params[ns.sql_name] = {p.param_name for p in ns.param_list}
        if typed_context is not None:
            context_types = {
                root.expr: _parse_rendered_type(root.return_type)
                for root in typed_context.root_values
                if root.source_type != "function"
            }
            function_types = {
                root.expr: _parse_rendered_type(root.return_type)
                for root in typed_context.root_values
                if root.source_type == "function"
            }
            fetch_return_types = {
                _extract_fetch_name(template.definition_expr):  _source_item_type(
                    _parse_rendered_type(template.return_type)
                )
                for template in typed_context.var_templates
                if _extract_fetch_name(template.definition_expr)
            }
        return AstValidationContext(
            context_registry=context_registry,
            context_types=context_types,
            bo_types=bo_types,
            function_types=function_types,
            fetch_return_types=fetch_return_types,
            function_params=function_params,
            fetch_params=fetch_params,
            type_registry=self.type_registry,
            method_registry=self.method_registry,
        )


def _source_item_type(type_ref: TypeRef) -> TypeRef:
    if type_ref.kind == "list" and type_ref.element_type is not None:
        return type_ref.element_type
    return type_ref


def _merge_sql_branch_env(
    target: FilteredEnvironment,
    source: FilteredEnvironment,
    loaded_resource: LoadedResource,
) -> None:
    """Merge SQL-branch filtered_env into the compiled env: dedup contexts, namingsql, and add BO fields."""
    existing_global_ids = {c.resource_id for c in target.selected_global_contexts}
    for ctx_item in source.selected_global_contexts:
        if ctx_item.resource_id not in existing_global_ids:
            target.selected_global_contexts.append(ctx_item)
            target.selected_global_context_ids.append(ctx_item.resource_id)
            existing_global_ids.add(ctx_item.resource_id)

    existing_local_ids = {c.resource_id for c in target.visible_local_context}
    for ctx_item in source.visible_local_context:
        if ctx_item.resource_id not in existing_local_ids:
            target.visible_local_context.append(ctx_item)
            target.selected_local_context_ids.append(ctx_item.resource_id)
            existing_local_ids.add(ctx_item.resource_id)

    existing_ns_names = {ns.naming_sql_name for ns in target.naming_sql_resources}
    for ns in source.naming_sql_resources:
        if ns.naming_sql_name not in existing_ns_names:
            target.naming_sql_resources.append(ns)
            existing_ns_names.add(ns.naming_sql_name)
    if source.naming_sql_params:
        target.naming_sql_params = list(source.naming_sql_params)

    bo_field_map: dict[str, set[str]] = {}
    for ns in source.naming_sql_resources:
        if not ns.bo_name:
            continue
        field_names = bo_field_map.setdefault(ns.bo_name, set())
        field_names.update(ns.condition_fields)

    existing_bo_names = {bo.bo_name for bo in target.selected_bos}
    for bo_name, field_names in bo_field_map.items():
        full_bo = loaded_resource.bo_registry.get(bo_name)
        if full_bo is None:
            continue
        if bo_name in existing_bo_names:
            bo = next(b for b in target.selected_bos if b.bo_name == bo_name)
            existing_fields = {p.field_name for p in bo.property_list}
            for prop in full_bo.property_list:
                if prop.field_name in field_names and prop.field_name not in existing_fields:
                    bo.property_list.append(prop)
                    existing_fields.add(prop.field_name)
        else:
            key_props = [prop for prop in full_bo.property_list if prop.data_type == DataTypeEnum.key]
            matched_props = [prop for prop in full_bo.property_list if prop.field_name in field_names]
            all_props = []
            seen = set()
            for prop in [*matched_props, *key_props]:
                if prop.field_name not in seen:
                    seen.add(prop.field_name)
                    all_props.append(prop)
            target.selected_bos.append(
                BoRegistry(
                    resource_id=full_bo.resource_id,
                    bo_name=full_bo.bo_name,
                    bo_desc=full_bo.bo_desc,
                    property_list=all_props,
                    naming_sql_list=full_bo.naming_sql_list,
                    select_list=full_bo.select_list,
                    tag=full_bo.tag,
                )
            )
            target.selected_bo_ids.append(full_bo.resource_id)
            existing_bo_names.add(bo_name)


def _call_with_retry_feedback(
    callback: Callable[..., Any],
    retry_feedback: dict[str, Any] | None,
    **kwargs: Any,
) -> Any:
    if retry_feedback is not None and _accepts_retry_feedback(callback):
        kwargs["retry_feedback"] = retry_feedback
    return callback(**kwargs)


def _accepts_retry_feedback(callback: Callable[..., Any]) -> bool:
    try:
        parameters = inspect.signature(callback).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.name == "retry_feedback"
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


def _build_retry_feedback(
    *,
    attempt: int,
    stage: str,
    error_type: str,
    message: str,
) -> dict[str, Any]:
    normalized_message = " ".join(message.split())[:MAX_RETRY_FEEDBACK_MESSAGE_LENGTH]
    return {
        "attempt": attempt,
        "stage": stage,
        "error_type": error_type,
        "message": normalized_message,
    }


def _parse_rendered_type(value: str) -> TypeRef:
    text = str(value or "").strip()
    if text.startswith("List<") and text.endswith(">"):
        return TypeRef(kind="list", element_type=_parse_rendered_type(text[5:-1]))
    if text.startswith("Map<") and text.endswith(">"):
        inner = text[4:-1]
        key, separator, val = inner.partition(",")
        if separator:
            return TypeRef(
                kind="map",
                key_type=_parse_rendered_type(key),
                value_type=_parse_rendered_type(val),
            )
    if "." in text:
        kind, name = text.split(".", 1)
        if kind in {"basic", "key", "bo", "logic", "extattr"} and name:
            return TypeRef(kind=kind, name=name)
    if text in {"void", "unknown"}:
        return TypeRef(kind=text)
    return TypeRef(kind="unknown")


def _type_ref_to_value_return_type(type_ref: TypeRef | None) -> ReturnType:
    if type_ref is None or type_ref.kind == "unknown":
        return _default_value_return_type()
    if type_ref.kind == "list":
        element = type_ref.element_type
        if element is None or element.kind == "unknown":
            return _default_value_return_type()
        return ReturnType(
            is_list=True,
            data_type=element.kind,
            data_type_name=element.name or "",
        )
    return ReturnType(
        is_list=False,
        data_type=type_ref.kind,
        data_type_name=type_ref.name or "",
    )


def _default_value_return_type() -> ReturnType:
    return ReturnType(is_list=False, data_type="basic", data_type_name="String")


def _extract_fetch_name(expression: str) -> str | None:
    match = re.match(r"^\s*(fetch_one|fetch)\(([^,\)]+)", str(expression or ""))
    if not match:
        return None
    return match.group(2).strip()


