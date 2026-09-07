from __future__ import annotations

import re

PLACEHOLDER_RE = re.compile(r"\{([A-Z0-9_]+)\}")


def render_template(template: str, values: dict[str, tuple[str, str]]) -> dict:
    output_parts: list[str] = []
    entities: list[dict] = []
    cursor = 0
    output_length = 0

    for match in PLACEHOLDER_RE.finditer(template):
        literal = template[cursor : match.start()]
        output_parts.append(literal)
        output_length += len(literal)

        placeholder = match.group(1)
        text, label = values[placeholder]

        start = output_length
        output_parts.append(text)
        output_length += len(text)
        end = output_length

        entities.append({"start": start, "end": end, "label": label})
        cursor = match.end()

    output_parts.append(template[cursor:])

    entities.sort(key=lambda entity: entity["start"])
    return {"text": "".join(output_parts), "entities": entities}
