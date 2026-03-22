# CSV Image Artifacts

## Overview

When the system writes a CSV artifact, it should also write a same-name PNG image so the result can be previewed quickly without opening spreadsheet software.

## Scope

- Add a shared CSV-to-image artifact helper.
- Generate a PNG alongside daily selection artifact CSV output.
- Generate a PNG alongside date-range aggregated daily-selection CSV output.
- Generate a PNG alongside stock-report CSV output.
- Add or update tests that verify the PNG files are created.

## Non-Goals

- No changes to strategy logic or selection ranking.
- No changes to JSON artifact contracts.
- No requirement to perfectly reproduce spreadsheet formatting.

## Affected Files or Components

- `src/tw_quant/workflows.py`
- `src/tw_quant/runner.py`
- `src/tw_quant/reporting/` (new helper module)
- `tests/test_tw_quant_daily_selection_runtime.py`
- `tests/test_tw_quant_runner_daily_selection_range.py`
- `tests/test_tw_quant_stock_report_contracts.py`

## Implementation Steps

1. Add a reusable helper that accepts CSV fieldnames and rows, then renders a table-like PNG beside the CSV file.
2. Use optional dependency behavior:
- if image rendering libraries are unavailable, keep CSV output working and skip PNG generation safely,
- when rendering is available, return the PNG path.
3. Wire the helper into:
- daily-selection artifact CSV persistence,
- range summary CSV writing,
- stock-report CSV writing.
4. Keep the existing CSV column order and CSV content unchanged.

## Acceptance Criteria

- Writing a daily-selection artifact CSV also creates a same-stem PNG file in the same folder.
- Writing a date-range daily-selection CSV with `--output-csv` also creates a same-stem PNG file.
- Writing a stock-report CSV with `--output-csv` also creates a same-stem PNG file.
- Existing CSV content and field order remain unchanged.
- Added tests pass.

## Open Questions

- None.
