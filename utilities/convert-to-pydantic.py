"""Conversion utilities to convert Java structs to Python Pydantic base models."""

import re
from pathlib import Path


def convert_java_to_pydantic(java_source: str) -> str:
    """Convert a java struct to pydantic base model."""
    # Pattern captures type, name, and optional assignment value
    field_pattern = re.compile(r"public\s+([\w\[\]<>, ]+)\s+(\w+)(?:\s*=\s*([^;]+))?\s*;")

    type_mapping = {
        "String": "str",
        "Integer": "int",
        "int": "int",
        "Byte": "int",
        "Boolean": "bool",
        "Double": "float",
        "Float": "float",
        "Long": "int",
    }

    fields = field_pattern.findall(java_source)

    output = [
        "from typing import Optional, Any",
        "from pydantic import BaseModel, ConfigDict",
        "",
        "class ProductParams(BaseModel):",
        "    model_config = ConfigDict(extra='forbid')",
        "",
    ]

    for java_type, name, default_val in fields:
        default_val = default_val.strip() if default_val else "None"

        if "HashMap" in java_type:
            inner = re.search(r"<(.*)>", java_type).group(1)
            parts = [p.strip() for p in inner.split(",")]
            k = type_mapping.get(parts[0], "Any")
            v = type_mapping.get(parts[1], "Any")
            final_type = f"dict[{k}, {v}] | None"

        elif "[][]" in java_type:
            base = type_mapping.get(java_type.replace("[][]", ""), "Any")
            final_type = f"list[list[{base}]] | None"

        elif "[]" in java_type:
            base = java_type.replace("[]", "")
            py_type = type_mapping.get(base, "Any")
            if py_type == "str":
                final_type = "list[str] | str | None"
            else:
                final_type = f"list[{py_type}] | None"

        else:
            py_type = type_mapping.get(java_type, "Any")
            if "null" in default_val:
                final_type = f"{py_type} | None"
                default_val = None
            elif default_val != "None":
                final_type = py_type  # Remove Optional if hard default exists
            else:
                final_type = f"{py_type} | None"

        output.append(f"    {name}: {final_type} = {default_val}")

    text = "\n".join(output)
    text = text.replace("null", "None")

    return text


product_finder_path = Path(
    "~/source/api_backend/src/main/java/com/keepa/api/backend/structs/ProductFinderRequest.java"
).expanduser()

with product_finder_path.open() as fid:
    product_finder_src = fid.read()

print(convert_java_to_pydantic(product_finder_src))
