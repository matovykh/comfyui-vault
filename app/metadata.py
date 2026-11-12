"""Conservative, source-attributed descriptions of a ComfyUI execution graph."""
import json


SAMPLER_FIELDS = ("seed", "noise_seed", "steps", "cfg", "sampler_name", "scheduler", "denoise",
                  "start_at_step", "end_at_step", "add_noise", "guidance", "width", "height", "batch_size")


def is_link(value, graph):
    return (isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int))
            and str(value[0]) in graph and isinstance(value[1], int))


def ancestors(graph, root):
    result, stack = set(), [str(root)]
    while stack:
        node_id = stack.pop()
        if node_id in result or node_id not in graph:
            continue
        result.add(node_id)
        for value in graph[node_id].get("inputs", {}).values():
            if is_link(value, graph):
                stack.append(str(value[0]))
    return result


def describe(graph, root=None, overrides=None):
    graph = {str(k): v for k, v in graph.items()}
    used = ancestors(graph, root) if root is not None else set(graph)
    prompts, samplers, loras, dimensions, unresolved = [], [], [], [], []

    def resolve(value, trail=None):
        if not is_link(value, graph):
            return value, "literal"
        node_id = str(value[0])
        trail = set() if trail is None else trail
        if node_id in trail:
            return None, "unresolved"
        trail.add(node_id)
        node = graph[node_id]
        # Only constant nodes: never infer the output of an arbitrary computing node.
        if node.get("class_type") in {"PrimitiveNode", "PrimitiveString", "PrimitiveInt", "PrimitiveFloat",
                                      "PrimitiveStringMultiline", "StringConstant", "INTConstant", "FloatConstant"}:
            inputs = node.get("inputs", {})
            for key in ("value", "string", "text", "int", "float"):
                if key in inputs:
                    return resolve(inputs[key], trail)
        return None, "unresolved"

    for node_id, node in graph.items():
        if node_id not in used:
            continue
        kind, inputs = node.get("class_type", "?"), node.get("inputs", {})
        title = node.get("_meta", {}).get("title", kind)
        base = {"node_id": node_id, "class_type": kind, "title": title}
        fields = {}
        for key, value in inputs.items():
            if key in SAMPLER_FIELDS:
                actual, state = resolve(value)
                if state == "unresolved":
                    unresolved.append({**base, "field": key, "source": value})
                else:
                    # JSON numbers parsed by a browser lose uint64 precision.
                    fields[key] = str(actual) if key in {"seed", "noise_seed"} and isinstance(actual, int) else actual
            if key in {"text", "text_g", "text_l", "positive_prompt", "negative_prompt", "prompt"}:
                actual, state = resolve(value)
                if isinstance(actual, str):
                    prompts.append({**base, "field": key, "text": actual, "source": "graph"})
                elif state == "unresolved":
                    unresolved.append({**base, "field": key, "source": value})
        if fields:
            if any(x in fields for x in ("seed", "noise_seed", "steps", "sampler_name", "scheduler", "cfg")):
                samplers.append({**base, "parameters": fields})
            else:
                dimensions.append({**base, "parameters": fields})
        if "lora" in kind.lower() or "lora_name" in inputs:
            values = {}
            for key, value in inputs.items():
                actual, state = resolve(value)
                if state != "unresolved" and isinstance(actual, (str, int, float, bool, type(None))):
                    values[key] = actual
            loras.append({**base, "parameters": values})
    stages = []
    by_node = {item["node_id"]: item for item in samplers + dimensions}
    sampler_classes = {"KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced"}
    for node_id, node in graph.items():
        if node_id not in used or node.get("class_type") not in sampler_classes:
            continue
        direct = by_node.get(node_id, {}).get("parameters", {})
        parameters = dict(direct)
        sources = {key: [node_id] for key in direct}
        controls = set()
        stack = [str(value[0]) for key, value in node.get("inputs", {}).items()
                 if key in {"noise", "sampler", "sigmas", "guider"} and is_link(value, graph)]
        while stack:
            key = stack.pop()
            if key in controls or graph[key].get("class_type") in sampler_classes:
                continue
            controls.add(key)
            for field, value in graph[key].get("inputs", {}).items():
                if field not in {"model", "positive", "negative", "latent", "latent_image", "image", "images", "samples"} and is_link(value, graph):
                    stack.append(str(value[0]))
        candidates = {}
        for key in controls:
            for field, value in by_node.get(key, {}).get("parameters", {}).items():
                candidates.setdefault(field, []).append((key, value))
        for field, values in candidates.items():
            if field not in parameters and len({str(v) for _, v in values}) == 1:
                parameters[field] = values[0][1]
                sources[field] = [k for k, _ in values]
        stages.append({"node_id": node_id, "class_type": node["class_type"],
                       "title": node.get("_meta", {}).get("title", node["class_type"]),
                       "parameters": parameters, "sources": sources})
    return {"prompts": prompts, "samplers": stages or samplers, "parameter_nodes": samplers,
            "loras": loras, "dimensions": dimensions,
            "unresolved": unresolved, "explicit_values": browser_safe(overrides or {}), "used_node_ids": sorted(used)}


def browser_safe(value):
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
        return str(value)
    if isinstance(value, dict):
        return {k: browser_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [browser_safe(v) for v in value]
    return value


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
