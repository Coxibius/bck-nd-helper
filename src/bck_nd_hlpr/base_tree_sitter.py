class BaseTreeSitterVisitor:
    def __init__(self, source_bytes: bytes):
        self.source_bytes = source_bytes

    def visit(self, node):
        if node is None:
            return None
        method_name = f"visit_{node.type}"
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node):
        results = []
        for child in getattr(node, "children", []) or []:
            res = self.visit(child)
            if res is not None:
                results.append(res)
        return results

    def text(self, node):
        if node is None:
            return ""
        return self.source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")

    def child(self, node, node_type: str):
        if node is None:
            return None
        for c in getattr(node, "children", []) or []:
            if c.type == node_type:
                return c
        return None

    def children(self, node, node_type: str):
        if node is None:
            return []
        return [c for c in (getattr(node, "children", []) or []) if c.type == node_type]

    def descendants(self, node, node_type: str):
        matches = []

        def _walk(n):
            for c in getattr(n, "children", []) or []:
                if c.type == node_type:
                    matches.append(c)
                _walk(c)

        if node is not None:
            _walk(node)
        return matches