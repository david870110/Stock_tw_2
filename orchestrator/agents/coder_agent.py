"""
Vibe Coding Agent Orchestrator
Coder Agent – implements source code based on the approved spec.
"""
from __future__ import annotations

from orchestrator.agents.base_agent import BaseAgent
from orchestrator.models import PipelineContext
from orchestrator.utils import get_logger

logger = get_logger("vibe.coder")


class CoderAgent(BaseAgent):
    """
    The Coder reads the approved spec and Manager instructions, then
    implements the code and writes a summary log.
    Steps 6–7 (implementation phase).
    """

    name = "coder"
    system_prompt = (
        "You are the Coder in a Vibe Coding automated development pipeline. "
        "Your job is to implement exactly what the spec describes. "
        "Write clean, readable, well-documented code. "
        "Handle errors gracefully and never skip spec requirements. "
        "If the spec is ambiguous, implement a reasonable default and note it."
    )

    def implement(self, ctx: PipelineContext) -> str:
        """
        Read coder instructions and approved spec, then produce implementation output.

        In a real pipeline the Coder agent would write actual files to disk.
        Here the LLM produces the complete file contents as a markdown document
        containing fenced code blocks, which the pipeline then persists.

        Returns a markdown string describing all created files and their contents.
        """
        logger.info("[Coder] implementing code (iteration %d)", ctx.iteration)
        prompt = f"""
You are implementing code based on the following materials:

## Manager Instructions
{ctx.coder_instructions}

## Approved Code Spec
{ctx.approved_spec}

Your task:
1. Implement ALL files described in the spec.
2. For each file, output its FULL content in a fenced code block.
3. After all code, write a summary section.

Use this exact format for each file:

### `path/to/file.py`
```python
# full file content here
```

At the end, write a **## Coder Output Summary** section with:
- **Files Created / Modified**: list of paths
- **How to Run**: installation and execution commands
- **Notes**: any deviations from spec or known limitations

Implement EVERY file. Do not skip or summarise with "similar to above".
"""
        return self.chat(prompt)
