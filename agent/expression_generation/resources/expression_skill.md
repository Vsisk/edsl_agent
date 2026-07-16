# 全局表达式使用技巧

## 列表当前元素

skill_id: list-current-element
triggers: structural:parent_list

当当前字段位于 `parent_list.children` 内时，`$iter$` 表示最近一层列表的当前元素。
访问当前元素字段时使用 `$iter$.FIELD`。
嵌套列表中只能直接使用最近一层 `$iter$`；如需使用外层元素，应先在外层 `iter_local_context` 中保存，再通过 `$local$.变量名` 访问。

## Date 所在年份

skill_id: date-year
triggers: 年份, 所在年, year

获取 Date 类型值所在年份时使用：

```text
dateValue.addDays(1).toString("yyyy")
```

## Date 所在月份

skill_id: date-month
triggers: 月份, 所在月, month

获取 Date 类型值所在月份时使用：

```text
dateValue.addDays(1).toString("MM")
```
