# ComparePlugin for Sublime Text

A better plugin for for comparing files in Sublime Text 4.

---

## Features

| Feature | Details |
|---|---|
| Side-by-side diff | Opens a 2-column layout automatically |
| Added lines | Green background + dot gutter icon |
| Deleted lines | Red background + minus gutter icon |
| Changed lines | Yellow background + bookmark gutter icon |
| Blank padding lines | Dark grey – keeps both sides in sync visually |
| Block navigation | Jump to next/previous diff block |
| Synchronized scrolling | Both panes scroll together |
| Compare against saved | Diff the unsaved buffer vs. the on-disk version |
| Pick any two views | Quick panel to choose which files to compare |

---

## Installation

1. Open Sublime Text.
2. Go to **Preferences → Browse Packages…**
3. Create a new folder called `BetterCompare`.
4. Copy **all files** from this folder into it:

```
Packages/
  ComparePlugin/
    compare_plugin.py
    compare_plugin.sublime-commands
    compare_plugin.sublime-color-scheme
    Default.sublime-keymap
    Main.sublime-menu
    README.md
```


### Colour scheme

The plugin uses four custom scopes (`compare.added`, `compare.deleted`, `compare.changed`, `compare.blank`).

**Option A – merge into your existing colour scheme (recommended)**

Open your active `.sublime-color-scheme` file and add the four `rules` entries from `compare_plugin.sublime-color-scheme`.

**Option B – use the bundled scheme**

Add to your User Preferences (`Preferences → Settings`):

```json
"color_scheme": "Packages/ComparePlugin/compare_plugin.sublime-color-scheme"
```
Please note that colours are now added automatically - no need to add anything to color scheme/Preferences

---

## Usage

### Menu
**Compare Plugin** menu appears in the top menu bar under Tools.

### Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`)
Search for `Compare:` to see all commands.

### Keyboard shortcuts (default)

| Shortcut | Action |
|---|---|
| `Alt+D` | Compare last two active views |
| `Alt+Shift+D` | Select two files from a quick panel |
| `Alt+Shift+S` | Compare current buffer vs. saved file on disk |
| `Alt+Down` | Jump to next difference |
| `Alt+Up` | Jump to previous difference |
| `Alt+Shift+C` | Clear comparison and restore single-pane layout |

---

## How it works

1. `difflib.SequenceMatcher` computes the opcodes (equal / insert / delete / replace).
2. Both views are padded with blank lines so equal content sits on the same line number in both panes.
3. `view.add_regions()` applies coloured backgrounds via the four custom scopes.
4. A `CompareSession` tracks the current window's state and diff block index.
5. `CompareSyncScrollListener` keeps viewport positions in sync.

---

## Customising keybindings

Open **Preferences → Key Bindings** and add your overrides, e.g.:

```json
{ "keys": ["ctrl+alt+c"], "command": "compare" }
```

---

## Known limitations

- The padded content replaces the buffer temporarily; use **Clear Comparison** (`Alt+Shift+C`) to restore normal editing.
- Binary files are not supported.
