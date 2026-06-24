# Patch notes v3.1 - Dynamic worksheet names

- Parent worksheet names now use the configured regulation names instead of fixed `Fr 1 -> Fr2` and `Fr 2 -> Fr1`.
- Example: `FRAMEWORK_A_NAME=NIS2_France` and `FRAMEWORK_B_NAME=NIS2_Belgique` produce:
  - `NIS 2 France -> NIS 2 Belgique`
  - `NIS 2 Belgique -> NIS 2 France`
- Atomic detail sheets are automatically abbreviated to respect Excel's 31-character worksheet name limit, for example:
  - `Atomic NIS2 FR -> NIS2 BE`
  - `Atomic NIS2 BE -> NIS2 FR`
- Page titles and dashboard subtitles also display cleaned regulation names.
- Renaming the project folder is supported as long as the project is launched from its root folder and `.env` paths remain relative. If the virtual environment was created before renaming the folder, recreate it if activation fails.
