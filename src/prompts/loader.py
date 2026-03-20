from pathlib import Path
from typing import Optional


class PromptLoader:
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = Path(prompts_dir)

    def load_system_prompt(self, role: str) -> str:
        """Load the system prompt for a role (e.g., 'manager', 'planner')."""
        file_path = self.prompts_dir / f"{role.lower()}.md"
        if not file_path.exists():
            return f"You are the {role} agent."
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    def load_template(self, template_name: str) -> str:
        """Load a prompt template by name (e.g., 'manager_to_planner')."""
        file_path = self.prompts_dir / "templates" / f"{template_name}.md"
        if not file_path.exists():
            return "{title}\n{description}"
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    def render_template(self, template_name: str, **kwargs) -> str:
        """Load and render a template with provided variables using str.format()."""
        template = self.load_template(template_name)
        try:
            return template.format(**kwargs)
        except KeyError:
            # If some keys are missing, return the template as-is with available keys
            for key, value in kwargs.items():
                template = template.replace("{" + key + "}", str(value))
            return template
