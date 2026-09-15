# Expression Context Rules

Context resources are visible values available to the current node.

- Prefer local context when it directly satisfies the query.
- Include global context only when the query or target node semantics require it.
- Preserve return type metadata because generation and validation depend on it.
- Do not treat the complete context registry as a stage input.
