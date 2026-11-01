
import re

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class MissingVariables(Exception):
    def __init__(self, names: list[str]):
        self.names = names
        super().__init__(", ".join(names))


def template_variables(template: str) -> list[str]:
   
    seen: list[str] = []
    for name in PLACEHOLDER.findall(template):
        if name not in seen:
            seen.append(name)
    return seen


def render_template(template: str, variables: dict) -> str:
    missing = [name for name in template_variables(template) if name not in variables]
    if missing:
        raise MissingVariables(missing)
  
    return PLACEHOLDER.sub(lambda m: str(variables[m.group(1)]), template)
