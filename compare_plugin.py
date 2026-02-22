"""
ComparePlugin for Sublime Text 3/4
A better version of existing compare plugins in my opinion.

Compatible with Python 3.3 (Sublime Text 3) and Python 3.8 (Sublime Text 4).

Key design: the original file views are NEVER modified. The plugin creates
two temporary scratch views to display the padded diff, then closes them
on clear or when either is closed by the user.

Installation:
  Preferences > Browse Packages > create folder "BetterCompare"
  Copy all plugin files into that folder.
  Restart Sublime Text to load plugin

Usage:
  Tools > Compare (pick 2 files to compare against each other)
  Tools > Compare Plugin > Compare (Last Two Views)   or  Alt+D
  Tools > Compare Plugin > Select Files to Compare    or  Alt+Shift+D
  Tools > Compare Plugin > Compare Against Saved      or  Alt+Shift+S
  Alt+Down / Alt+Up  to navigate differences
  Alt+Shift+C        to clear
"""

import sublime
import sublime_plugin
import difflib

# ──────────────────────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────────────────────
# Region key names
KEY_ADDED   = "compare_added"

# Fill pattern for blank padding lines (mimics Visual Studio style)
BLANK_FILL  = "/" * 120
KEY_DELETED = "compare_deleted"
KEY_CHANGED = "compare_changed"
KEY_BLANK   = "compare_blank"
KEY_INLINE  = "compare_inline"  # character-level highlights inside changed lines

# Colours for diff regions
COLOR_ADDED   = "#1a3a1a"
COLOR_DELETED = "#3a1a1a"
COLOR_CHANGED = "#2e2a10"
COLOR_BLANK   = "#2A2D2F"
COLOR_INLINE  = "#FFEE00"   # bright yellow for intra-line char diffs

COLOR_ADDED_FG   = "#aaffaa"
COLOR_DELETED_FG = "#ffaaaa"
COLOR_CHANGED_FG = "#ffeeaa"
COLOR_BLANK_FG = "#4A4D4F"

# window_id -> CompareSession
_sessions = {}


# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────

def _full_region(view):
    return sublime.Region(0, view.size())

def _line_regions(view):
    return view.lines(_full_region(view))

def _get_lines(view):
    return view.substr(_full_region(view)).splitlines()

def _clear_highlights(view):
    for key in (KEY_ADDED, KEY_DELETED, KEY_CHANGED, KEY_BLANK, KEY_INLINE):
        view.erase_regions(key)

def _apply_highlights(view, added_lines, deleted_lines, changed_lines, blank_lines):
    line_regs = _line_regions(view)
    total = len(line_regs)
    def safe(indices):
        return [line_regs[i] for i in indices if i < total]
    # Use scope strings that embed the colour directly via add_regions' scope parameter.
    # In ST3/4, when a scope is not found in the colour scheme, add_regions falls back
    # to no colouring -- so we set a per-view colour scheme override on each display view.
    flags = sublime.DRAW_NO_OUTLINE
    view.add_regions(KEY_ADDED,   safe(added_lines),   "compare.added",   "dot",      flags)
    view.add_regions(KEY_DELETED, safe(deleted_lines), "compare.deleted", "dot",      flags)
    view.add_regions(KEY_CHANGED, safe(changed_lines), "compare.changed", "bookmark", flags)
    view.add_regions(KEY_BLANK,   safe(blank_lines),   "compare.blank",   "",         flags)


def _apply_inline_highlights(left_view, right_view, changed_pairs):
    """
    For each pair of changed lines, do a character-level diff and highlight
    the specific characters that differ in both views.
    """
    left_regs  = _line_regions(left_view)
    right_regs = _line_regions(right_view)
    left_total  = len(left_regs)
    right_total = len(right_regs)

    left_inline  = []
    right_inline = []

    for (li, ri, ltext, rtext) in changed_pairs:
        if li >= left_total or ri >= right_total:
            continue
        # Get the start offset of each line in the view
        l_line_start = left_regs[li].begin()
        r_line_start = right_regs[ri].begin()

        # Character-level diff using SequenceMatcher
        matcher = difflib.SequenceMatcher(None, ltext, rtext, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            # Highlight changed/deleted chars on the left
            if i1 < i2:
                left_inline.append(
                    sublime.Region(l_line_start + i1, l_line_start + i2)
                )
            # Highlight changed/inserted chars on the right
            if j1 < j2:
                right_inline.append(
                    sublime.Region(r_line_start + j1, r_line_start + j2)
                )

    flags = sublime.DRAW_NO_OUTLINE
    left_view.add_regions(KEY_INLINE,  left_inline,  "compare.inline", "", flags)
    right_view.add_regions(KEY_INLINE, right_inline, "compare.inline", "", flags)


def _apply_view_color_scheme(view):
    """
    Write a standalone .tmTheme with a neutral dark background and our
    4 diff scopes. No theme inheritance — avoids any colour bleed from
    the user's active theme.
    """
    import os

    fname    = "ComparePlugin.tmTheme"
    fpath    = os.path.join(sublime.packages_path(), "User", fname)
    pkg_path = "Packages/User/" + fname

    # Neutral dark background/foreground — matches most dark themes well
    BG = "#1D1F21"
    FG = "#D4D4D4"

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0">',
        '<dict>',
        '	<key>name</key><string>ComparePlugin</string>',
        '	<key>settings</key>',
        '	<array>',
        '		<dict>',
        '			<key>settings</key>',
        '			<dict>',
        '				<key>background</key><string>' + BG + '</string>',
        '				<key>foreground</key><string>' + FG + '</string>',
        '				<key>caret</key><string>#AEAFAD</string>',
        '				<key>lineHighlight</key><string>#2A2A2A</string>',
        '				<key>selection</key><string>#264F78</string>',
        '			</dict>',
        '		</dict>',
    ]

    def scope_entry(name, scope, bg, fg):
        return [
            '		<dict>',
            '			<key>name</key><string>' + name + '</string>',
            '			<key>scope</key><string>' + scope + '</string>',
            '			<key>settings</key>',
            '			<dict>',
            '				<key>background</key><string>' + bg + '</string>',
            '				<key>foreground</key><string>' + fg + '</string>',
            '			</dict>',
            '		</dict>',
        ]

    lines += scope_entry("Compare Added",   "compare.added",   COLOR_ADDED,   COLOR_ADDED_FG)
    lines += scope_entry("Compare Deleted", "compare.deleted", COLOR_DELETED, COLOR_DELETED_FG)
    lines += scope_entry("Compare Changed", "compare.changed", COLOR_CHANGED, COLOR_CHANGED_FG)
    lines += scope_entry("Compare Blank",   "compare.blank",   COLOR_BLANK,   COLOR_BLANK_FG)
    lines += scope_entry("Compare Inline",  "compare.inline",  COLOR_INLINE,  "#000000")

    lines += [
        '	</array>',
        '</dict>',
        '</plist>',
    ]

    try:
        with open(fpath, "w", encoding="utf-8") as fh:
            fh.write(chr(10).join(lines))
        view.settings().set("color_scheme", pkg_path)
    except Exception as e:
        print("ComparePlugin: could not write tmTheme: " + str(e))

def _set_view_content(view, content):
    view.run_command("compare_set_content", {"content": content})

def _scroll_to_line(view, line_idx):
    regs = _line_regions(view)
    if line_idx < len(regs):
        view.show_at_center(regs[line_idx])
        view.sel().clear()
        view.sel().add(regs[line_idx].begin())


# ──────────────────────────────────────────────────────────────
#  Diff engine
# ──────────────────────────────────────────────────────────────

class DiffResult(object):
    def __init__(self):
        self.left_lines   = []
        self.right_lines  = []
        self.left_marks   = {"added": [], "deleted": [], "changed": [], "blank": []}
        self.right_marks  = {"added": [], "deleted": [], "changed": [], "blank": []}
        self.diff_blocks  = []
        self.changed_pairs = []  # list of (left_line_idx, right_line_idx, left_text, right_text)


def compute_diff(left_lines, right_lines):
    result  = DiffResult()
    matcher = difflib.SequenceMatcher(None, left_lines, right_lines, autojunk=False)
    l_out, r_out = [], []
    l_added, l_deleted, l_changed, l_blank = [], [], [], []
    r_added, r_deleted, r_changed, r_blank = [], [], [], []
    li = ri = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                l_out.append(left_lines[i1 + k])
                r_out.append(right_lines[j1 + k])
                li += 1
                ri += 1
        elif tag == "insert":
            result.diff_blocks.append((li, ri))
            for k in range(j2 - j1):
                l_out.append(BLANK_FILL)
                r_out.append(right_lines[j1 + k])
                l_blank.append(li)
                r_added.append(ri)
                li += 1
                ri += 1
        elif tag == "delete":
            result.diff_blocks.append((li, ri))
            for k in range(i2 - i1):
                l_out.append(left_lines[i1 + k])
                r_out.append(BLANK_FILL)
                l_deleted.append(li)
                r_blank.append(ri)
                li += 1
                ri += 1
        elif tag == "replace":
            result.diff_blocks.append((li, ri))
            lcount = i2 - i1
            rcount = j2 - j1
            for k in range(max(lcount, rcount)):
                lline = left_lines[i1 + k]  if k < lcount else BLANK_FILL
                rline = right_lines[j1 + k] if k < rcount else BLANK_FILL
                l_out.append(lline)
                r_out.append(rline)
                if k < lcount and k < rcount:
                    l_changed.append(li); r_changed.append(ri)
                    result.changed_pairs.append((li, ri, lline, rline))
                elif k < lcount:
                    l_deleted.append(li); r_blank.append(ri)
                else:
                    l_blank.append(li);  r_added.append(ri)
                li += 1
                ri += 1

    result.left_lines  = l_out
    result.right_lines = r_out
    result.left_marks  = {"added": l_added, "deleted": l_deleted,
                          "changed": l_changed, "blank": l_blank}
    result.right_marks = {"added": r_added, "deleted": r_deleted,
                          "changed": r_changed, "blank": r_blank}
    return result


# ──────────────────────────────────────────────────────────────
#  Session
#  Tracks the two SCRATCH display views (not the original files)
# ──────────────────────────────────────────────────────────────

class CompareSession(object):
    def __init__(self, source_window, compare_window, left_display, right_display, diff):
        self.source_window = source_window   # original window (source files live here)
        self.window        = compare_window  # dedicated compare window
        self.left_display  = left_display    # scratch view showing left diff
        self.right_display = right_display   # scratch view showing right diff
        self.diff          = diff
        self.block_index   = 0

    def current_block(self):
        if not self.diff.diff_blocks:
            return None
        return self.diff.diff_blocks[self.block_index]

    def next_block(self):
        if not self.diff.diff_blocks:
            return None
        self.block_index = (self.block_index + 1) % len(self.diff.diff_blocks)
        return self.current_block()

    def prev_block(self):
        if not self.diff.diff_blocks:
            return None
        self.block_index = (self.block_index - 1) % len(self.diff.diff_blocks)
        return self.current_block()

    def display_view_ids(self):
        return (self.left_display.id(), self.right_display.id())


# ──────────────────────────────────────────────────────────────
#  Core runner
#  Creates two SCRATCH views for the diff. Original views
#  are read-only sources and are never modified.
# ──────────────────────────────────────────────────────────────

def run_compare(source_window, left_source, right_source):
    # Close any existing session from this source window first
    _close_session_by_source(source_window.id())

    diff = compute_diff(_get_lines(left_source), _get_lines(right_source))

    # Build display names
    def display_name(view):
        fname = view.file_name()
        if fname:
            name = fname.replace("\\", "/").split("/")[-1]
        else:
            name = view.name() or "untitled"
        return "[Compare] " + name

    # Open a brand new window dedicated to this comparison
    before_ids = set(w.id() for w in sublime.windows())
    sublime.run_command("new_window")
    compare_window = None
    for w in sublime.windows():
        if w.id() not in before_ids:
            compare_window = w
            break
    if compare_window is None:
        # fallback — should never happen
        compare_window = sublime.active_window()

    # Create two scratch views inside the new window
    left_display  = compare_window.new_file()
    right_display = compare_window.new_file()

    left_display.set_scratch(True)
    right_display.set_scratch(True)
    left_display.set_read_only(True)
    right_display.set_read_only(True)
    left_display.set_name(display_name(left_source))
    right_display.set_name(display_name(right_source))

    # Copy syntax so code highlighting looks right
    left_syntax  = left_source.settings().get("syntax")
    right_syntax = right_source.settings().get("syntax")
    if left_syntax:
        left_display.set_syntax_file(left_syntax)
    if right_syntax:
        right_display.set_syntax_file(right_syntax)

    # Enable minimap on both display views
    for dv in (left_display, right_display):
        dv.settings().set("minimap", True)
        dv.settings().set("word_wrap", False)

    # Side-by-side layout in the compare window
    compare_window.set_layout({
        "cols":  [0.0, 0.5, 1.0],
        "rows":  [0.0, 1.0],
        "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]
    })

    # new_window starts with one empty untitled view — close it
    for v in compare_window.views():
        if v.id() not in (left_display.id(), right_display.id()):
            v.set_scratch(True)
            v.close()

    compare_window.set_view_index(left_display,  0, 0)
    compare_window.set_view_index(right_display, 1, 0)

    # Write padded diff content
    left_display.set_read_only(False)
    right_display.set_read_only(False)
    _set_view_content(left_display,  "\n".join(diff.left_lines))
    _set_view_content(right_display, "\n".join(diff.right_lines))
    left_display.set_read_only(True)
    right_display.set_read_only(True)

    # Apply diff highlights and per-view colour scheme
    _apply_highlights(left_display,
                      diff.left_marks["added"],   diff.left_marks["deleted"],
                      diff.left_marks["changed"], diff.left_marks["blank"])
    _apply_highlights(right_display,
                      diff.right_marks["added"],   diff.right_marks["deleted"],
                      diff.right_marks["changed"], diff.right_marks["blank"])
    _apply_inline_highlights(left_display, right_display, diff.changed_pairs)
    _apply_view_color_scheme(left_display)
    _apply_view_color_scheme(right_display)

    session = CompareSession(source_window, compare_window, left_display, right_display, diff)
    # Key by BOTH the source window and the compare window so we can look up either way
    _sessions[source_window.id()]  = session
    _sessions[compare_window.id()] = session

    _last_vp[left_display.id()]  = left_display.viewport_position()
    _last_vp[right_display.id()] = right_display.viewport_position()
    _start_fast_poll()

    count = len(diff.diff_blocks)
    compare_window.status_message(
        "Compare: " + str(count) + " difference(s) found. "
        "Close this window or press Alt+Shift+C to finish."
    )
    if diff.diff_blocks:
        _scroll_to_line(left_display,  diff.diff_blocks[0][0])
        _scroll_to_line(right_display, diff.diff_blocks[0][1])


def _close_session(window_id, close_views=True):
    """Tear down a session by either the source or compare window id."""
    session = _sessions.pop(window_id, None)
    if not session:
        return
    # Remove the other key too so nothing recurses
    _sessions.pop(session.source_window.id(), None)
    _sessions.pop(session.window.id(), None)

    if close_views:
        # Close each scratch view individually.
        # When the last view in the compare window closes,
        # Sublime closes that window automatically — without
        # touching any other window.
        for v in (session.left_display, session.right_display):
            try:
                v.set_read_only(False)
                v.set_scratch(True)
                v.close()
            except Exception:
                pass


def _close_session_by_source(source_window_id):
    """Close whatever compare session belongs to a given source window."""
    _close_session(source_window_id, close_views=True)


# ──────────────────────────────────────────────────────────────
#  Internal text command: write content into a view
# ──────────────────────────────────────────────────────────────

class CompareSetContentCommand(sublime_plugin.TextCommand):
    def run(self, edit, content=""):
        self.view.replace(edit, _full_region(self.view), content)
    def is_visible(self):
        return False


# ──────────────────────────────────────────────────────────────
#  User-facing commands
# ──────────────────────────────────────────────────────────────

class CompareFilesCommand(sublime_plugin.WindowCommand):
    """Compare the two most recently active views.  Command: compare_files"""
    def run(self):
        views  = self.window.views()
        active = self.window.active_view()
        others = [v for v in views if v.id() != active.id()]
        if not others:
            sublime.error_message("Compare: need at least two open files.")
            return
        run_compare(self.window, others[-1], active)
    def is_enabled(self):
        return True
    def is_visible(self):
        return True


class CompareSelectFilesCommand(sublime_plugin.WindowCommand):
    """Pick any two open views to compare.  Command: compare_select_files"""
    def run(self):
        # Rename command palette entry text to "Compare" when triggered
        # Build the file list excluding any active compare display views
        active_ids = set()
        session = _sessions.get(self.window.id())
        if session:
            active_ids = set(session.display_view_ids())

        self._views = [v for v in self.window.views() if v.id() not in active_ids]
        self._names = [
            v.file_name() or v.name() or ("<untitled " + str(v.id()) + ">")
            for v in self._views
        ]
        self._selected = []

        # Step 1: ask for first file
        self.window.show_quick_panel(
            self._names,
            self._on_first,
            placeholder="Compare: select the 1st file"
        )

    def _on_first(self, idx):
        if idx == -1:
            return
        self._selected.append(idx)

        # Refresh the file list (user may have switched tabs between picks)
        active_ids = set()
        session = _sessions.get(self.window.id())
        if session:
            active_ids = set(session.display_view_ids())
        self._views = [v for v in self.window.views() if v.id() not in active_ids]
        self._names = [
            v.file_name() or v.name() or ("<untitled " + str(v.id()) + ">")
            for v in self._views
        ]

        # Find the view that was picked in step 1 by name match
        first_name = (
            self._views[self._selected[0]].file_name() or
            self._views[self._selected[0]].name() or
            "<untitled " + str(self._views[self._selected[0]].id()) + ">"
        ) if self._selected[0] < len(self._views) else ""

        # Step 2: ask for second file
        self.window.show_quick_panel(
            self._names,
            self._on_second,
            placeholder="Compare: select the 2nd file (first: " + first_name.split("/")[-1].split("\\")[-1] + ")"
        )

    def _on_second(self, idx):
        if idx == -1:
            return
        # Re-resolve the first view by index from the refreshed list
        first_idx = self._selected[0]
        if first_idx >= len(self._views) or idx >= len(self._views):
            sublime.error_message("Compare: could not resolve selected files.")
            return
        run_compare(self.window, self._views[first_idx], self._views[idx])

    def is_enabled(self):
        return True
    def is_visible(self):
        return True


class CompareAgainstSavedCommand(sublime_plugin.WindowCommand):
    """Compare current buffer against the file saved on disk.  Command: compare_against_saved"""
    def run(self):
        view  = self.window.active_view()
        fname = view and view.file_name()
        if not fname:
            sublime.error_message("Compare: file has not been saved yet.")
            return
        try:
            fh = open(fname, "r", encoding="utf-8", errors="replace")
            saved = fh.read()
            fh.close()
        except OSError as e:
            sublime.error_message("Compare: cannot read saved file.\n" + str(e))
            return
        # Create a temporary source view for the saved version
        saved_view = self.window.new_file()
        saved_view.set_scratch(True)
        saved_view.set_name("[Saved] " + fname.replace("\\", "/").split("/")[-1])
        _set_view_content(saved_view, saved)
        run_compare(self.window, saved_view, view)
        # Close the temporary source view now that diff is computed
        saved_view.close()

    def is_enabled(self):
        return True
    def is_visible(self):
        return True


class CompareNextDiffCommand(sublime_plugin.WindowCommand):
    """Jump to next difference.  Command: compare_next_diff"""
    def run(self):
        session = _sessions.get(self.window.id())
        if not session:
            sublime.status_message("Compare: no active comparison.")
            return
        block = session.next_block()
        if block:
            _scroll_to_line(session.left_display,  block[0])
            _scroll_to_line(session.right_display, block[1])
            sublime.status_message(
                "Compare: difference " +
                str(session.block_index + 1) + "/" +
                str(len(session.diff.diff_blocks))
            )
    def is_enabled(self):
        return True
    def is_visible(self):
        return True


class ComparePrevDiffCommand(sublime_plugin.WindowCommand):
    """Jump to previous difference.  Command: compare_prev_diff"""
    def run(self):
        session = _sessions.get(self.window.id())
        if not session:
            sublime.status_message("Compare: no active comparison.")
            return
        block = session.prev_block()
        if block:
            _scroll_to_line(session.left_display,  block[0])
            _scroll_to_line(session.right_display, block[1])
            sublime.status_message(
                "Compare: difference " +
                str(session.block_index + 1) + "/" +
                str(len(session.diff.diff_blocks))
            )
    def is_enabled(self):
        return True
    def is_visible(self):
        return True



# ──────────────────────────────────────────────────────────────
#  Mark & Compare (tab right-click workflow)
#
#  Right-click any open tab -> "Mark for Compare"
#  Right-click another tab  -> "Compare with Marked"
#  The marked view is stored per-window.
# ──────────────────────────────────────────────────────────────

_marked = {}        # window_id -> view
_marked_names = {}  # view_id -> original tab name


def _unmark_tab(view):
    original = _marked_names.pop(view.id(), None)
    try:
        view.set_name(original if original is not None else "")
    except Exception:
        pass


def _get_marked(window):
    v = _marked.get(window.id())
    if v is None:
        return None
    # Check the view is still open in this window
    open_ids = set(x.id() for x in window.views())
    if v.id() not in open_ids:
        _marked_names.pop(v.id(), None)
        _marked.pop(window.id(), None)
        return None
    return v


class CompareMarkCommand(sublime_plugin.TextCommand):
    """Right-click a tab -> Mark for Compare.  Command: compare_mark"""
    def run(self, edit):
        window = self.view.window()
        if not window:
            return
        # Unmark previous tab in this window if different
        prev = _marked.get(window.id())
        if prev and prev.id() != self.view.id():
            _unmark_tab(prev)
        _marked[window.id()] = self.view
        fname = self.view.file_name()
        name  = fname.replace("\\", "/").split("/")[-1] if fname else (self.view.name() or "untitled")
        # Prefix tab name with >> marker
        if not self.view.name().startswith(">> "):
            _marked_names[self.view.id()] = self.view.name()
            self.view.set_name(">> " + name)
        sublime.status_message("Compare: marked \"" + name + "\" — right-click another tab and choose \"Compare with Marked\"")

    def is_enabled(self):
        return True

    def is_visible(self):
        return True


class CompareWithMarkedCommand(sublime_plugin.TextCommand):
    """Right-click a tab -> Compare with Marked.  Command: compare_with_marked"""
    def run(self, edit):
        window = self.view.window()
        if not window:
            return
        marked = _get_marked(window)
        if marked is None:
            sublime.error_message("Compare: no file marked yet.\nRight-click a tab and choose \"Mark for Compare\" first.")
            return
        if marked.id() == self.view.id():
            sublime.error_message("Compare: cannot compare a file with itself.")
            return
        run_compare(window, marked, self.view)
        _unmark_tab(marked)
        _marked.pop(window.id(), None)

    def is_enabled(self):
        window = self.view.window()
        if not window:
            return False
        return _get_marked(window) is not None

    def is_visible(self):
        return True

    def description(self):
        window = self.view.window() if self.view else None
        if not window:
            return "Compare with Marked"
        marked = _get_marked(window)
        if not marked:
            return "Compare with Marked"
        fname = marked.file_name()
        name  = fname.replace("\\", "/").split("/")[-1] if fname else (marked.name() or "untitled")
        return "Compare with Marked: \"" + name + "\""


class CompareClearCommand(sublime_plugin.WindowCommand):
    """Close compare window.  Command: compare_clear"""
    def run(self):
        _close_session(self.window.id(), close_views=True)
        sublime.status_message("Compare: cleared.")
    def is_enabled(self):
        return True
    def is_visible(self):
        return True


# ──────────────────────────────────────────────────────────────
#  Close listener
#  When the user closes one of the scratch diff views directly,
#  clean up the session and close the other one too.
# ──────────────────────────────────────────────────────────────

class CompareCloseListener(sublime_plugin.EventListener):

    def on_pre_close_window(self, window):
        """When the compare window is closed by the user, clean up the session."""
        session = _sessions.get(window.id())
        if session and window.id() == session.window.id():
            # Remove both keys so nothing tries to re-close
            _sessions.pop(session.source_window.id(), None)
            _sessions.pop(session.window.id(), None)

    def on_pre_close(self, view):
        # Fallback: if a display view is closed individually, close whole session
        seen = set()
        for wid, session in list(_sessions.items()):
            if session.window.id() in seen:
                continue
            if view.id() in session.display_view_ids():
                seen.add(session.window.id())
                _sessions.pop(session.source_window.id(), None)
                _sessions.pop(session.window.id(), None)
                # Close the peer view; Sublime auto-closes the window
                # when its last view is gone
                if view.id() == session.left_display.id():
                    peer = session.right_display
                else:
                    peer = session.left_display
                try:
                    peer.set_read_only(False)
                    peer.set_scratch(True)
                    peer.close()
                except Exception:
                    pass
                break


def _restore_layout(window):
    pass   # layout lives in the compare window which closes itself


# ──────────────────────────────────────────────────────────────
#  Synchronized scrolling
# ──────────────────────────────────────────────────────────────

_syncing     = set()
_poll_active = False
_last_vp     = {}


def _sync_peer(source_view):
    if source_view.id() in _syncing:
        return
    window = source_view.window()
    if not window:
        return
    session = _sessions.get(window.id())
    if not session:
        return
    if source_view.id() == session.left_display.id():
        peer = session.right_display
    elif source_view.id() == session.right_display.id():
        peer = session.left_display
    else:
        return
    _syncing.add(peer.id())
    try:
        peer.set_viewport_position(source_view.viewport_position(), animate=False)
    finally:
        _syncing.discard(peer.id())


class CompareSyncListener(sublime_plugin.ViewEventListener):

    @classmethod
    def is_applicable(cls, settings):
        return True

    def _is_display_view(self):
        window = self.view.window()
        if not window:
            return False
        session = _sessions.get(window.id())
        if not session:
            return False
        return self.view.id() in session.display_view_ids()

    def on_post_text_command(self, command_name, args):
        if self._is_display_view():
            _sync_peer(self.view)

    def on_activated(self):
        if self._is_display_view():
            _sync_peer(self.view)
            _start_fast_poll()


def _start_fast_poll():
    global _poll_active
    if _poll_active:
        return
    _poll_active = True
    sublime.set_timeout(_fast_poll_tick, 8)


def _fast_poll_tick():
    global _poll_active

    if not _sessions:
        _poll_active = False
        _last_vp.clear()
        return

    for session in _sessions.values():
        lv = session.left_display
        rv = session.right_display
        try:
            lp = lv.viewport_position()
            rp = rv.viewport_position()
        except Exception:
            continue

        l_prev = _last_vp.get(lv.id())
        r_prev = _last_vp.get(rv.id())
        l_moved = l_prev is not None and (lp[0] != l_prev[0] or lp[1] != l_prev[1])
        r_moved = r_prev is not None and (rp[0] != r_prev[0] or rp[1] != r_prev[1])

        if l_moved and lv.id() not in _syncing:
            _syncing.add(rv.id())
            try:
                rv.set_viewport_position(lp, animate=False)
            finally:
                _syncing.discard(rv.id())
            _last_vp[rv.id()] = lp
        elif r_moved and rv.id() not in _syncing:
            _syncing.add(lv.id())
            try:
                lv.set_viewport_position(rp, animate=False)
            finally:
                _syncing.discard(lv.id())
            _last_vp[lv.id()] = rp

        _last_vp[lv.id()] = lv.viewport_position()
        _last_vp[rv.id()] = rv.viewport_position()

    sublime.set_timeout(_fast_poll_tick, 8)


def _start_sync_poll():
    _start_fast_poll()


# ──────────────────────────────────────────────────────────────
#  Colour scheme injection
#
#  Sublime Text supports a per-user colour scheme override file
#  (Packages/User/<name>.sublime-color-scheme) that MERGES its
#  rules on top of any active theme without replacing it.
#  We write ours on plugin_loaded and remove it on plugin_unloaded.
# ──────────────────────────────────────────────────────────────

import os
import json

_SCHEME_FILENAME = "ComparePlugin.sublime-color-scheme"




def _scheme_path():
    """Return the full path to the User packages override file."""
    packages_path = sublime.packages_path()
    return os.path.join(packages_path, "User", _SCHEME_FILENAME)


def _install_color_scheme():
    """
    Write a merged .sublime-color-scheme into Packages/User/.
    ST3.1+ merges this on top of the active theme automatically.
    """
    path = _scheme_path()
    data = {
        "name": "ComparePlugin colours",
        "variables": {},
        "globals": {},
        "rules": [
            {"name": "Compare Added",   "scope": "compare.added",
             "background": COLOR_ADDED,   "foreground": COLOR_ADDED_FG},
            {"name": "Compare Deleted", "scope": "compare.deleted",
             "background": COLOR_DELETED, "foreground": COLOR_DELETED_FG},
            {"name": "Compare Changed", "scope": "compare.changed",
             "background": COLOR_CHANGED, "foreground": COLOR_CHANGED_FG},
            {"name": "Compare Blank",   "scope": "compare.blank",
             "background": COLOR_BLANK,   "foreground": COLOR_BLANK_FG}
        ]
    }
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=4)
        print("ComparePlugin: colour scheme written to " + path)
    except Exception as e:
        print("ComparePlugin: could not write colour scheme: " + str(e))


def _remove_color_scheme():
    """Remove all generated colour scheme files when the plugin is unloaded."""
    for fname in ("ComparePlugin.sublime-color-scheme", "ComparePlugin.tmTheme"):
        path = os.path.join(sublime.packages_path(), "User", fname)
        try:
            if os.path.exists(path):
                os.remove(path)
                print("ComparePlugin: removed " + fname)
        except Exception as e:
            print("ComparePlugin: could not remove " + fname + ": " + str(e))


def plugin_loaded():
    global _poll_active
    _sessions.clear()
    _last_vp.clear()
    _syncing.clear()
    _marked.clear()
    _marked_names.clear()
    _poll_active = False
    _install_color_scheme()
    import sys
    print("ComparePlugin loaded OK (Python " + sys.version + ")")

def plugin_unloaded():
    global _poll_active
    _poll_active = False
    # Close all scratch display views cleanly
    for wid in list(_sessions.keys()):
        _close_session(wid, close_views=True)
    _sessions.clear()
    _last_vp.clear()
    _syncing.clear()
    _marked.clear()
    _marked_names.clear()
    _remove_color_scheme()
