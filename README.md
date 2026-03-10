# Stock_tw_2 — Vibe Coding Agent

A fully automated **Vibe Coding** pipeline powered by four GitHub Copilot custom agents:
**Manager → Planner → Coder → QA**.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Orchestrator (Python)                     │
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ Manager  │───▶│ Planner  │    │  Coder   │    │    QA    │  │
│  │  Agent   │◀───│  Agent   │    │  Agent   │    │  Agent   │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       │                               ▲               │         │
│       └───────────────────────────────┘               │         │
│                   logs/                               │         │
│  (manager_analysis, planner_spec, coder_output, qa_output, …)  │
└──────────────────────────────────────────────────────────────────┘
```

### Agents

| Agent | Role | Definition |
|-------|------|-----------|
| **Manager** | Coordinates the whole pipeline, reviews outputs, decides next action | `.github/agents/manager.md` |
| **Planner** | Produces a detailed Code Spec from Manager instructions | `.github/agents/planner.md` |
| **Coder** | Implements all source code based on the approved spec | `.github/agents/coder.md` |
| **QA** | Tests the implementation and issues a PASS / FAIL / SPEC_UNCLEAR verdict | `.github/agents/qa.md` |

---

## The 9-Step Pipeline

```
Step 1  [Manager]  Analyse task → break into subtasks
Step 2  [Manager]  Create Planner instructions
Step 3  [Manager]  Hand instructions to Planner  (log file)
Step 4  [Planner]  Write Code Spec               → logs/planner_spec.md
Step 5  [Manager]  Review spec → produce approved spec → logs/approved_spec.md
Step 6  [Manager]  Create Coder instructions → hand to Coder
Step 7  [Coder]    Implement code             → logs/coder_output.md
        [Manager]  Create QA instructions    → logs/qa_instructions.md
Step 8  [QA]       Test implementation        → logs/qa_output.md
Step 9  [Manager]  Evaluate QA result:
            PASS         → ✅ Pipeline complete
            FAIL         → ⚠️  Re-dispatch Coder (up to max_iterations)
            SPEC_UNCLEAR → ⚠️  Re-dispatch Planner (up to max_iterations)
```

---

## Project Structure

```
.
├── .github/
│   ├── agents/
│   │   ├── manager.md          ← Manager agent definition
│   │   ├── planner.md          ← Planner agent definition
│   │   ├── coder.md            ← Coder agent definition
│   │   └── qa.md               ← QA agent definition
│   └── workflows/
│       └── vibe-coding-pipeline.yml   ← GitHub Actions trigger
├── orchestrator/
│   ├── __init__.py
│   ├── main.py                 ← CLI entry point
│   ├── pipeline.py             ← 9-step state machine
│   ├── models.py               ← Data models & enums
│   ├── config.py               ← Configuration (env vars)
│   ├── agents/
│   │   ├── base_agent.py       ← OpenAI wrapper
│   │   ├── manager_agent.py
│   │   ├── planner_agent.py
│   │   ├── coder_agent.py
│   │   └── qa_agent.py
│   └── utils/
│       ├── logger.py
│       └── file_handler.py
├── tests/
│   └── test_pipeline.py        ← Unit tests (no API key needed)
├── logs/                       ← Agent communication logs (git-ignored)
├── tasks/                      ← Task definitions (git-ignored)
├── requirements.txt
└── requirements-dev.txt
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- An OpenAI API key (or a compatible API)

### Installation

```bash
pip install -r requirements.txt
```

### Run a pipeline

```bash
export OPENAI_API_KEY="sk-..."

python -m orchestrator.main run \
  --title "Build a todo REST API" \
  --description "Create a FastAPI application with CRUD endpoints for a todo list, using SQLite for storage."
```

### Check pipeline status

```bash
python -m orchestrator.main status
```

### Resume an interrupted pipeline

```bash
python -m orchestrator.main resume
```

---

## Configuration (Environment Variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | *(required)* | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API base URL (use for Azure / local LLMs) |
| `VIBE_MODEL` | `gpt-4o` | LLM model to use |
| `VIBE_TEMPERATURE` | `0.2` | Sampling temperature |
| `VIBE_MAX_TOKENS` | `4096` | Max tokens per agent call |
| `VIBE_MAX_ITERATIONS` | `3` | Max retry cycles before pipeline fails |
| `VIBE_LOGS_DIR` | `logs` | Directory for agent log files |
| `VIBE_TASKS_DIR` | `tasks` | Directory for task files |
| `VIBE_STATE_FILE` | `logs/pipeline_state.json` | Pipeline state file path |

---

## GitHub Actions

The pipeline can be triggered via **Actions → Vibe Coding Pipeline → Run workflow**.

Required repository secret:
- `OPENAI_API_KEY`

Optional repository variable:
- `VIBE_MODEL` (defaults to `gpt-4o`)

After the run, all log files are uploaded as workflow artifacts.

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Tests mock all LLM calls and run without an API key.

---

## Log Files

After each pipeline run, `logs/` contains:

| File | Written by | Contents |
|------|-----------|---------|
| `manager_analysis.md` | Manager | Task breakdown & subtasks |
| `planner_instructions.md` | Manager | Brief for Planner |
| `planner_spec.md` | Planner | Raw Code Spec |
| `approved_spec.md` | Manager | Reviewed & approved spec |
| `coder_instructions.md` | Manager | Coding instructions |
| `coder_output.md` | Coder | All implemented files + summary |
| `qa_instructions.md` | Manager | QA test instructions |
| `qa_output.md` | QA | Test report + verdict |
| `pipeline_result.md` | Manager | Final decision & reasoning |
| `pipeline_state.json` | Orchestrator | Full pipeline state (resume support) |
| `orchestrator.log` | Orchestrator | Detailed execution log |