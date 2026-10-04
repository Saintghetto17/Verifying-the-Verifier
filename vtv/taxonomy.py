"""Defect taxonomy: normalized operator tags and affected-object tags.

The machine-learning subset carries free-form Russian defect descriptions
(``gold.lies``). They are mapped to ten normalized operator tags by the
keyword rules below. A single injection may receive several tags, so the tags
are mentions, not a partition of the pairs. The biotechnology and cross-domain
subsets keep the free-form English labels of their source annotations; for
cross-subset comparisons those labels are mapped to the same ten operators via
``SOURCE_LABEL_TO_OPERATOR``.
"""

from __future__ import annotations

import re

OPERATORS: tuple[str, ...] = (
    "label_text_edit",
    "element_deletion",
    "block_permutation",
    "edge_rewiring",
    "content_replacement",
    "generic_edit",
    "geometric_distortion",
    "element_addition",
    "value_fabrication",
    "restyling",
)

OPERATOR_NAMES: dict[str, str] = {
    "label_text_edit": "Label and in-figure text edit",
    "element_deletion": "Element deletion",
    "block_permutation": "Block permutation",
    "edge_rewiring": "Edge rewiring",
    "content_replacement": "Content replacement",
    "generic_edit": "Generic edit",
    "geometric_distortion": "Geometric distortion",
    "element_addition": "Element addition",
    "value_fabrication": "Value fabrication",
    "restyling": "Restyling",
}

OBJECTS: tuple[str, ...] = ("blocks", "labels", "images", "plots", "arrows", "axes")

# Each comma/semicolon-separated clause of a description receives exactly one
# tag: the first rule (in priority order) whose pattern matches the clause.
_OPERATOR_RULES: tuple[tuple[str, str], ...] = (
    ("element_deletion", r"удал|убран"),
    ("element_addition", r"добавл|дублир"),
    ("block_permutation", r"перемеш|пермеш|перемещ|порядок|местоположени"),
    ("edge_rewiring", r"стрел|связ"),
    ("value_fabrication", r"числ|значени|диапазон|данные"),
    ("geometric_distortion", r"отзеркал|поверн|искаж|инверт"),
    ("restyling", r"цвет|палитр|стилистик|шкал"),
    ("content_replacement", r"замен|подмен|полност|полнстью|загружен|"
                            r"(график|изображен|рисун)\w*\s+измен|"
                            r"измен\w*\s+(\d-е\s+|правое\s+|правый\s+)?(график|изображен|рисун)"),
    ("label_text_edit", r"подпис|одпис|надпис|текст|назван|индекс|уравнен|описание|обозначен|содерж|метк"),
)

_OBJECT_RULES: tuple[tuple[str, str], ...] = (
    ("blocks", r"блок"),
    ("labels", r"подпис|надпис|текст|назван|обозначен|метк|индекс"),
    ("images", r"изображен|рисун|картин|фото"),
    ("plots", r"график|диаграм|грвфик|граифк"),
    ("arrows", r"стрел|связ"),
    ("axes", r"\bос[ьиейя]\b|шкал|абсцисс|ординат"),
)


def ml_operators(description: str) -> list[str]:
    """Normalized operator tags for one Russian free-form description."""
    tags: set[str] = set()
    previous: str | None = None
    for clause in re.split(r"[,;|]", description.lower()):
        if not clause.strip():
            continue
        tag = next((name for name, pattern in _OPERATOR_RULES if re.search(pattern, clause)), None)
        if tag is None:
            # A verbless continuation ("удалены стрелки, блоки") shares the
            # operator of the preceding clause.
            verbless = not re.search(r"измен|исправ", clause)
            tag = previous if (previous and verbless) else "generic_edit"
        tags.add(tag)
        previous = tag
    return [op for op in OPERATORS if op in tags] or ["generic_edit"]


def ml_objects(description: str) -> list[str]:
    text = description.lower()
    return [name for name, pattern in _OBJECT_RULES if re.search(pattern, text)]


SOURCE_LABEL_TO_OPERATOR: dict[str, str] = {
    # biotechnology (bench_l2_folders) labels
    "labels changed": "label_text_edit",
    "axis labels changed": "label_text_edit",
    "in-figure text/content changed": "label_text_edit",
    "formulas changed": "label_text_edit",
    "units changed": "label_text_edit",
    "element deleted": "element_deletion",
    "elements swapped or reordered": "block_permutation",
    "arrows changed": "edge_rewiring",
    "plot replaced with a different one": "content_replacement",
    "image distorted": "geometric_distortion",
    "image mirrored or rotated": "geometric_distortion",
    "element added": "element_addition",
    "figure duplicated": "element_addition",
    "numeric values changed": "value_fabrication",
    "scale changed": "value_fabrication",
    "colours changed": "restyling",
    "texture changed": "restyling",
    "image quality degraded": "restyling",
    # cross-domain (bench_final) labels
    "elements deleted": "element_deletion",
    "element occluded": "element_deletion",
    "labels replaced with nonsense": "label_text_edit",
    "in-figure text changed": "label_text_edit",
    "legend changed": "label_text_edit",
    "elements swapped": "block_permutation",
    "content replaced": "content_replacement",
    "content replaced from another figure": "content_replacement",
}


def source_operators(labels: list[str]) -> list[str]:
    tags = {SOURCE_LABEL_TO_OPERATOR.get(label.strip().lower(), "generic_edit") for label in labels}
    return [op for op in OPERATORS if op in tags]
