"""Label presets: the class palette used to attribute cells as they are picked.

A *preset* is a named class ("schools", "pasture", "absent") that carries the
attribute values written alongside the cell. Its name is the value stored in
the schema's label field.

The attribute fields belong to the *schema*, not to individual classes: adding
"name" adds it for every class at once, and a class that leaves it blank writes
NULL. So the palette is a table — one row per class, one column per field —
rather than a bag of per-class key/value pairs, which is both what the data
looks like on disk and the only way to keep the field names consistent.

An ordered list of presets is a `PresetSchema`, serialised as JSON into the
`gridclick/presets` custom property of the layer it labels — so the schema
travels with the dataset in the .qgz rather than living in the session.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Dict, List, Optional

from qgis.core import QgsApplication, QgsField, QgsFields, QgsVectorLayer
from qgis.PyQt.QtCore import QVariant

PROP_PRESETS = "gridclick/presets"

#: default name of the field holding the class
F_LABEL = "label"
#: provenance fields, added to labelled layers only
F_CREATED = "created_at"
F_AUTHOR = "author"

#: presets 1..9 are reachable from the keyboard while the map tool is active
MAX_HOTKEYS = 9

#: Okabe-Ito, chosen because label classes must stay distinguishable to
#: colour-blind readers; cycled if a schema has more classes than colours.
PALETTE = [
    "#E69F00", "#56B4E9", "#009E73", "#F0E442",
    "#0072B2", "#D55E00", "#CC79A7", "#999999",
]


def palette_colour(index: int) -> str:
    return PALETTE[index % len(PALETTE)]


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
@dataclass
class Preset:
    #: also the value written to the schema's label field
    name: str
    colour: str = PALETTE[0]
    #: value per schema field; missing or "" writes NULL
    values: Dict[str, str] = field(default_factory=dict)

    def value(self, field_name: str) -> str:
        return self.values.get(field_name, "")

    def to_dict(self) -> dict:
        d = {"name": self.name, "colour": self.colour}
        if self.values:
            d["values"] = dict(self.values)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Preset":
        # "extra" is the v1 spelling, when fields were declared per class
        values = d.get("values") or d.get("extra") or {}
        return Preset(
            name=str(d.get("name", "")),
            colour=str(d.get("colour") or PALETTE[0]),
            values={str(k): ("" if v is None else str(v)) for k, v in values.items()},
        )


@dataclass
class PresetSchema:
    label_field: str = F_LABEL
    #: attribute columns, shared by every class, in display order
    fields: List[str] = field(default_factory=list)
    presets: List[Preset] = field(default_factory=list)
    #: record who created each label and when
    provenance: bool = True

    # ---- queries ----
    def is_empty(self) -> bool:
        return not self.presets

    def index_of(self, name: str) -> int:
        for i, p in enumerate(self.presets):
            if p.name == name:
                return i
        return -1

    def get(self, name: str) -> Optional[Preset]:
        i = self.index_of(name)
        return self.presets[i] if i >= 0 else None

    def field_names(self) -> List[str]:
        """Every field this schema writes, label field first, in order and
        without duplicates."""
        names = [self.label_field]
        for name in self.fields:
            if name and name not in names:
                names.append(name)
        if self.provenance:
            names += [F_CREATED, F_AUTHOR]
        return names

    # ---- editing the columns ----
    def add_field(self, name: str) -> bool:
        name = name.strip()
        if not name or name in self.fields or name == self.label_field:
            return False
        self.fields.append(name)
        return True

    def remove_field(self, name: str) -> bool:
        if name not in self.fields:
            return False
        self.fields.remove(name)
        for preset in self.presets:
            preset.values.pop(name, None)
        return True

    def rename_field(self, old: str, new: str) -> bool:
        new = new.strip()
        if old not in self.fields or not new or new == self.label_field:
            return False
        if new in self.fields and new != old:
            return False
        self.fields[self.fields.index(old)] = new
        for preset in self.presets:
            if old in preset.values:
                preset.values[new] = preset.values.pop(old)
        return True

    def unique_name(self, base: str = "class") -> str:
        if self.index_of(base) < 0:
            return base
        n = 2
        while self.index_of(f"{base} {n}") >= 0:
            n += 1
        return f"{base} {n}"

    def next_colour(self) -> str:
        return palette_colour(len(self.presets))

    # ---- (de)serialisation ----
    def to_json(self) -> str:
        return json.dumps(
            {
                "version": 2,
                "label_field": self.label_field,
                "provenance": self.provenance,
                "fields": list(self.fields),
                "presets": [p.to_dict() for p in self.presets],
            },
            ensure_ascii=False,
        )

    @staticmethod
    def from_json(text: str) -> Optional["PresetSchema"]:
        """Parse a stored schema; None if it is absent or unreadable (a bad
        custom property must not stop the plugin loading)."""
        if not text:
            return None
        try:
            d = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(d, dict):
            return None
        presets = [p for p in (Preset.from_dict(p) for p in d.get("presets", [])
                               if isinstance(p, dict)) if p.name]
        fields = [str(f) for f in d.get("fields", []) if str(f)]
        if not fields:
            # v1 declared fields per class; recover the columns from their union
            for preset in presets:
                for key in preset.values:
                    if key not in fields:
                        fields.append(key)
        return PresetSchema(
            label_field=str(d.get("label_field") or F_LABEL),
            fields=fields,
            presets=presets,
            provenance=bool(d.get("provenance", True)),
        )

    def copy(self) -> "PresetSchema":
        return replace(
            self,
            fields=list(self.fields),
            presets=[replace(p, values=dict(p.values)) for p in self.presets],
        )


def default_schema() -> PresetSchema:
    """The palette a fresh labelling session starts from."""
    return PresetSchema(
        label_field=F_LABEL,
        fields=[],
        presets=[
            Preset("class 1", palette_colour(0)),
            Preset("class 2", palette_colour(1)),
        ],
    )


# --------------------------------------------------------------------------- #
# layer storage
# --------------------------------------------------------------------------- #
def load_schema(layer: Optional[QgsVectorLayer]) -> Optional[PresetSchema]:
    if layer is None:
        return None
    return PresetSchema.from_json(layer.customProperty(PROP_PRESETS))


def save_schema(layer: QgsVectorLayer, schema: Optional[PresetSchema]) -> None:
    if layer is None:
        return
    if schema is None or schema.is_empty():
        layer.removeCustomProperty(PROP_PRESETS)
    else:
        layer.setCustomProperty(PROP_PRESETS, schema.to_json())


# --------------------------------------------------------------------------- #
# fields
# --------------------------------------------------------------------------- #
def schema_fields(schema: Optional[PresetSchema]) -> QgsFields:
    """Fields a schema needs, all string: labels are categorical, and a user
    who wants another type can change it in QGIS — `coerce` writes into
    whatever type the layer actually has."""
    fields = QgsFields()
    if schema is None:
        return fields
    for name in schema.field_names():
        fields.append(QgsField(name, QVariant.String, len=128))
    return fields


def missing_fields(layer: QgsVectorLayer, schema: Optional[PresetSchema]) -> List[str]:
    if layer is None or schema is None or schema.is_empty():
        return []
    have = {f.name() for f in layer.fields()}
    return [n for n in schema.field_names() if n not in have]


def add_missing_fields(layer: QgsVectorLayer, schema: Optional[PresetSchema]):
    """Add the schema's absent fields to `layer`. Returns (added, error)."""
    missing = missing_fields(layer, schema)
    if not missing:
        return [], ""
    new = [QgsField(n, QVariant.String, len=128) for n in missing]
    if layer.isEditable():
        ok = all(layer.addAttribute(f) for f in new)
    else:
        ok = layer.dataProvider().addAttributes(new)
        layer.updateFields()
    if not ok:
        return [], f"Could not add fields to '{layer.name()}'."
    layer.updateFields()
    return missing, ""


def coerce(value, qtype):
    """Convert a preset's string value to the type of the field it lands in."""
    if value is None:
        return None
    text = str(value)
    if qtype in (QVariant.Int, QVariant.LongLong, QVariant.ULongLong):
        try:
            return int(text)
        except ValueError:
            return None
    if qtype == QVariant.Double:
        try:
            return float(text)
        except ValueError:
            return None
    if qtype == QVariant.Bool:
        return text.strip().lower() in ("1", "true", "yes", "y", "t")
    return text


# --------------------------------------------------------------------------- #
# the values a click writes
# --------------------------------------------------------------------------- #
def author_name() -> str:
    return QgsApplication.userFullName() or QgsApplication.userLoginName() or ""


def attributes_for(schema: Optional[PresetSchema], preset: Optional[Preset]) -> Dict[str, str]:
    """field -> value for one click. Every declared field appears, blank ones
    as None, so re-labelling a cell replaces the whole attribute tuple instead
    of leaving values behind from the class it used to be.

    Provenance is stamped per call, so an updated label carries the time it was
    corrected."""
    if schema is None or preset is None:
        return {}
    attrs = {schema.label_field: preset.name}
    for name in schema.fields:
        value = preset.value(name)
        attrs[name] = value if value != "" else None
    if schema.provenance:
        attrs[F_CREATED] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        attrs[F_AUTHOR] = author_name()
    return attrs
