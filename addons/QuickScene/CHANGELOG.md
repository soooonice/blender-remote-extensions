# QuickScene — Changelog

## [1.2.1] - 2026-11-12

### Improved
- Remove leading name icons while retaining the confirmed compact native layout.
- Independently size scene and view-layer columns from their names, with width limits.
- Recalculate column widths immediately after renaming.
- Retain BACK / ADD / REMOVE actions and alphabetical ordering.
- Release completed popup timers and avoid duplicate sorting.
- Stop measuring names once the column width limit is reached.
- Use a dedicated popup operator and fresh keymap references for cleanup.

### Validation
- Registration, re-registration, cleanup and core operations tested in Blender 5.3.0 Beta.
- Original extension identity and minimum-version metadata retained.

## [1.2.0] - 2026-11-10

### Added
- Compact two-column scene/view-layer browser with alphabetical ordering.
- Rename, creation-options and confirmed deletion buttons on every row.
- Scene creation: New, Copy Settings, Linked Copy, Full Copy.
- View-layer creation: New, Copy Settings, Blank.

### Improved
- Active name buttons are highlighted while retaining the original icons.
- No headings, filtering toolbar or list-height drag controls.
- Recreate the browser after deletion/cancellation to recalculate its height.
- Validate stale targets and retain at least one scene/view layer.
- Robust registration and shortcut cleanup; retain the global V shortcut.

### Validation
- Core operations tested with Blender 5.3.0 Beta; minimum-version metadata retained.


## [1.0.3] - 2026-11-04

### Fixed
unexpected indent (__init__.py, line 41)


## [1.0.2] - 2026-11-04

### test


## [1.0.1] - 2026-11-04

### Improved
- Added custom tooltips for scene and view layer switching.
- Improved operator registration and shortcut cleanup.

### Fixed
- Fixed the "Undocumented operator" tooltip.

## [1.0.0] - 2026-11-04

### Initial Release
- Added global `V` shortcut.
- Added scene switching popup.
- Added view layer switching.
- Supported Blender 5.2 and later.