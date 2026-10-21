"""Strict collection edits used by both the spectrum manager and AI."""

import math
import re


def validate_style(value):
    if not isinstance(value, dict) or set(value) - {
        "color",
        "width",
        "line",
        "visible",
    }:
        raise ValueError("Styl spektra smí obsahovat barvu, šířku, typ čáry a viditelnost.")
    if "visible" in value and not isinstance(value["visible"], bool):
        raise ValueError("Viditelnost musí být logická hodnota.")
    if "color" in value and (
        not isinstance(value["color"], str)
        or not re.fullmatch(r"#[0-9a-fA-F]{6}", value["color"])
    ):
        raise ValueError("Barva musí mít tvar #RRGGBB.")
    if "width" in value:
        width = value["width"]
        if (
            isinstance(width, bool)
            or not isinstance(width, (int, float))
            or not math.isfinite(width)
            or not 0.1 <= width <= 100
        ):
            raise ValueError("Šířka čáry musí být v rozsahu 0,1 až 100.")
    if "line" in value and value["line"] not in ("solid", "dash", "dot", "dashdot"):
        raise ValueError("Neznámý typ čáry.")
    return dict(value)


def validate_collection(value, ids=None):
    if not isinstance(value, dict) or set(value) - {"rename", "order", "styles"}:
        raise ValueError("Správa spekter podporuje rename, order a styles.")
    for key in ("rename", "styles"):
        mapping = value.get(key, {})
        if not isinstance(mapping, dict) or len(mapping) > 1000:
            raise ValueError("Neplatné změny spekter.")
        for sid, item in mapping.items():
            if (
                not isinstance(sid, str)
                or not sid
                or (ids is not None and sid not in ids)
            ):
                raise ValueError("Návrh odkazuje na neznámé spektrum.")
            if key == "rename" and (
                not isinstance(item, str) or not item.strip() or len(item) > 1024
            ):
                raise ValueError("Název spektra musí mít 1 až 1024 znaků.")
            if key == "styles":
                validate_style(item)
    if "order" in value:
        order = value["order"]
        if (
            not isinstance(order, list)
            or not all(isinstance(s, str) for s in order)
            or len(order) != len(set(order))
            or (ids is not None and set(order) != set(ids))
        ):
            raise ValueError(
                "Pořadí musí obsahovat každé načtené spektrum právě jednou."
            )
    return value
