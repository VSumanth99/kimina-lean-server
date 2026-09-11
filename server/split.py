from typing import Tuple


def split_snippet(code: str) -> Tuple[str, str]:
    """
    Splits a code snippet into a header (imports) and body.

    - Header: leading imports, module/prelude declarations, and blank lines.
      If any import starts with 'import Mathlib', include a single 'import Mathlib' at the top of the header.
      Other imports follow in their original order, without duplicates.
    - Body: the rest of the code starting from the first non-import/non-blank line.
    """
    lines = code.splitlines()
    import_prefixes = ("import ", "public import ", "meta import ", "public meta import ")

    # Separate header from body
    i = 0
    while i < len(lines) and (
        lines[i].strip() in ("", "module", "prelude")
        or lines[i].strip().startswith(import_prefixes)
    ):
        i += 1
    header_lines = [x.strip() for x in lines[:i]]
    body = "\n".join(lines[i:])

    # Module headers must be replayed only when creating the import environment.
    # Preserve their visibility modifiers instead of rewriting them as plain imports.
    if any(
        line in ("module", "prelude")
        or line.startswith(("public import ", "meta import ", "public meta import "))
        for line in header_lines
    ):
        return "\n".join(header_lines), body

    # Process imports in header
    import_lines = [line for line in header_lines if line.startswith("import ")]
    imports: list[str] = []
    seen: set[str] = set()
    has_mathlib = False
    for line in import_lines:
        if line.startswith("import Mathlib"):
            has_mathlib = True
        else:
            if line not in seen:
                seen.add(line)
                imports.append(line)

    # Build final header
    result_header: list[str] = []
    if has_mathlib:
        result_header.append("import Mathlib")
    result_header.extend(imports)

    header = "\n".join(result_header)
    return header, body
