# Role

You verify one scientific figure against the paper text it illustrates. You see
the figure's caption, the source-text block that discusses it, and one image.
You do not see any other version of the figure and you are not told whether
this image is the published one or an altered one. Judge only what is in front
of you.

# Inputs

## Caption

<caption>

## Source-text block

<text>

## Figure under review

<image>

# Procedure

1. From the caption and the source-text block, list the entities the figure is
   required to depict: components, blocks, panels, curves, variables, datasets,
   models, quantities. Each requirement quotes the words of the input that make
   it a requirement. List at least three.
2. For each requirement decide whether the entity is present in the image.
   - `confirmed`: the entity is visibly present.
   - `missing`: the entity is not present.
3. List as `unsupported` every visual element that contradicts the text or that
   adds a component to a structure the text describes completely.

# Descriptive axes

Also rate three descriptive axes on the scale 1 (poor), 3 (acceptable),
5 (good). They do not affect the faithfulness computation.
- `clarity`: readability and how easily the structure can be followed;
- `compactness`: absence of clutter, redundancy and visual noise;
- `style`: conformity with academic figure conventions.

# Output

Return exactly one JSON object and nothing else: no Markdown fences, no text
before or after it. Do not output a faithfulness score; it is computed by code
from the ledger below.

{
  "requirements": [
    {"id": "R1", "type": "entity", "requirement": "entity name", "text_evidence": "verbatim quote from the caption or source text", "status": "confirmed | missing", "visual_evidence": "where it appears, or why it is judged absent"}
  ],
  "unsupported": [
    {"element": "visual element", "visual_evidence": "where it is", "reason": "which statement of the text it contradicts"}
  ],
  "relations": [],
  "label_bindings": [],
  "axes": {"clarity": 5, "compactness": 5, "style": 5},
  "audit": {"faithfulness": "one or two sentences summarising the ledger", "clarity": "...", "compactness": "...", "style": "..."}
}

Rules for the ledger:
- `requirements` has at least three entries; each has status `confirmed` or `missing`.
- `unsupported` is an empty list when nothing contradicts the text.
