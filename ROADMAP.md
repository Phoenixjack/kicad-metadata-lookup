# KiCad Metadata Lookup Roadmap

KML is a focused experiment for provider-backed metadata lookup before the workflow is folded into KiCad Import Assistant and, later, KiCARR.

## Framework Direction

Use PySide6 for the GUI. It gives KML a stronger path toward the later KiCARR app shell than Tkinter while still being practical for a small desktop utility.

Avoid the blank command prompt by launching the GUI with `pythonw.exe` or a `.pyw` entry point during development. When packaged, use a no-console build target such as PyInstaller's windowed mode.

## Milestone 1 - Repository And Config Baseline

- Keep the README minimal.
- Track only a safe private-data example file.
- Ignore the real local private-data file that contains API keys.
- Define the initial provider/key structure without wiring live API calls.
- Confirm that missing private data can be created from the example template.

## Milestone 2 - Minimal GUI Shell

- Create a PySide6 window with tabs or sections for Lookup, Results, Config, and Log.
- Add a `.pyw` launcher so normal GUI startup does not open a command prompt.
- Load and save `kml_private_data.json` only through explicit user action.
- Show provider-key status without revealing full secret values.

## Milestone 3 - Manual Lookup Workflow

- Accept a manufacturer part number and optional manufacturer name.
- Let the user choose which configured provider to query. (Initial Mouser lookup wired.)
- Show normalized results in a preview table.
- Do not write to KiCad files yet.
- Add clear empty, missing-key, provider-error, and rate-limit states.

## Milestone 4 - Provider Abstraction

- Define a shared provider interface for search, exact part lookup, and normalized metadata output.
- Start with one provider, likely Mouser, because KIA already models it as the first supported API.
- Add provider-specific request/auth code behind the shared interface.
- Normalize fields such as MPN, manufacturer, description, datasheet URL, product URL, lifecycle/status, package, category, and basic electrical attributes when available.

## Milestone 5 - Metadata Mapping

- Define KML's canonical metadata fields separately from provider response fields.
- Add confidence/source markers for every populated field.
- Support user review before accepting provider-supplied values.
- Preserve existing user-entered metadata unless replacement is explicitly selected.

## Milestone 6 - KIA Integration Prototype

- Export accepted lookup results as JSON that KIA can consume.
- Match KIA's private-config pattern for API keys.
- Add a small integration note or adapter contract, not a full KIA merge.
- Keep writes disabled until KIA-side preview and confirmation behavior is planned.

## Milestone 7 - KiCARR Readiness

- Keep provider logic UI-independent so it can become a shared core module later.
- Separate provider credentials, lookup history, normalized metadata, and GUI preferences.
- Document the minimum adapter surface KiCARR will need: configure providers, search by MPN, preview results, accept selected fields, and record provenance.

## Early Non-Goals

- No icon work.
- No detailed user documentation.
- No automatic KiCad library writes.
- No background service behavior.
- No committed API keys or local machine paths.
