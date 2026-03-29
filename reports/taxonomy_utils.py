def collect_descendant_ids(model, root_id: int) -> set[int]:
    ids = {root_id}
    frontier = [root_id]
    while frontier:
        children = list(
            model.objects.filter(predecessor_id__in=frontier).values_list("id", flat=True)
        )
        frontier = [child_id for child_id in children if child_id not in ids]
        ids.update(frontier)
    return ids


def taxonomy_choices(model):
    nodes = list(model.objects.select_related("predecessor").order_by("sort_order", "value"))
    by_id = {node.id: node for node in nodes}
    depth_cache: dict[int, int] = {}

    def _depth(node) -> int:
        cached = depth_cache.get(node.id)
        if cached is not None:
            return cached
        depth = 0
        seen = set()
        parent_id = node.predecessor_id
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            depth += 1
            parent = by_id.get(parent_id)
            if parent is None:
                break
            parent_id = parent.predecessor_id
        depth_cache[node.id] = depth
        return depth

    for node in nodes:
        node.display_name = f"{'-- ' * _depth(node)}{node.value}"
    return nodes
