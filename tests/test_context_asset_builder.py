import copy

from agent.context_manager.resolvers.resource import ResourceAssetBuilder
from agent.resource_manager.models import (
    BoRegistry, ContextRegistry, DataTypeEnum, FunctionRegistry, LocalContextRegistry,
    NamingSqlDefTerm, ParamTerm, ParamTypeTerm, PropertyTerm, ReturnType, ReturnTypeTerm,
)


def test_resource_builder_creates_semantic_stable_assets_without_mutation():
    field = PropertyTerm(field_name="CUST_ID", description="customer identifier", data_type=DataTypeEnum.basic, data_type_name="string")
    sql = NamingSqlDefTerm(naming_sql_id="n1", sql_name="findCustomer", sql_description="find customer", label_name="customer lookup", sql_command="SELECT secret", param_list=[ParamTerm(param_name="id", data_type_name="string")])
    bo = BoRegistry(resource_id="bo.1", bo_name="Customer", bo_desc="customer records", property_list=[field], naming_sql_list=[sql])
    global_ctx = ContextRegistry(resource_id="ctx.1", context_name="$ctx$.customer.id", return_type=ReturnType(data_type="basic", data_type_name="string"), property_type="system", annotation="current customer")
    local_ctx = LocalContextRegistry(resource_id="local.1", context_name="$ctx$.local.total", return_type=ReturnType(data_type="basic", data_type_name="decimal"), annotation="running total", source_path="$.node")
    iter_ctx = LocalContextRegistry(resource_id="iter.1", context_name="$iter$.line", return_type=ReturnType(data_type="bo", data_type_name="Line"), annotation="current line", property_type="iter")
    func = FunctionRegistry(resource_id="fn.1", func_name="mask", func_class="Text", func_desc="mask text", param_list=[ParamTypeTerm(param_name="value", data_type=DataTypeEnum.basic, data_type_name="string")], return_type=ReturnTypeTerm(data_type=DataTypeEnum.basic, data_type_name="string"))
    originals = [copy.deepcopy(item.model_dump()) for item in (bo, global_ctx, local_ctx, iter_ctx, func)]
    builder = ResourceAssetBuilder()

    assets = [builder.bo(bo), builder.bo_field("Customer", field), builder.naming_sql("Customer", sql), builder.context(global_ctx), builder.context(local_ctx), builder.context(iter_ctx), builder.function(func)]

    assert [a.asset_id for a in assets] == ["bo:Customer", "bo_field:Customer:CUST_ID", "naming_sql:Customer:n1", "context:ctx.1", "context:local.1", "context:iter.1", "function:Text:mask"]
    assert [a.asset_type for a in assets] == ["bo", "bo_field", "naming_sql", "global_context", "local_context", "iter_context", "function"]
    assert [a.scope for a in assets] == ["global", "global", "global", "global", "node", "node", "global"]
    assert all(a.source == "resource_registry" for a in assets)
    assert "customer records" in assets[0].index_text and "CUST_ID" in assets[0].index_text
    assert all(not a.index_text.lstrip().startswith("{") for a in assets)
    assert "find customer" in assets[2].index_text and "id" in assets[2].index_text and "string" in assets[2].index_text
    assert "SELECT secret" not in assets[2].index_text
    assert "current customer" in assets[3].index_text and "string" in assets[3].index_text
    assert "Text" in assets[6].index_text and "mask text" in assets[6].index_text
    assert assets[0].content == bo.model_dump(mode="json")
    assert assets[2].content == {"bo_name": "Customer", **sql.model_dump(mode="json")}
    assert assets[3].content == global_ctx.model_dump(mode="json")
    assert assets[6].content == func.model_dump(mode="json")
    assert assets[2].content["sql_command"] == "SELECT secret"
    assert [item.model_dump() for item in (bo, global_ctx, local_ctx, iter_ctx, func)] == originals
