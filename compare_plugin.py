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
KEY_ADDED   = "compare_added"
BLANK_FILL  = "/" * 120
KEY_DELETED = "compare_deleted"
KEY_CHANGED = "compare_changed"
KEY_BLANK   = "compare_blank"
KEY_INLINE  = "compare_inline"

COLOR_ADDED   = "#1a3a1a"
COLOR_DELETED = "#3a1a1a"
COLOR_CHANGED = "#2e2a10"
COLOR_BLANK   = "#2A2D2F"
COLOR_INLINE  = "#FFEE00"

COLOR_ADDED_FG   = "#aaffaa"
COLOR_DELETED_FG = "#ffaaaa"
COLOR_CHANGED_FG = "#ffeeaa"
COLOR_BLANK_FG   = "#4A4D4F"

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
    flags = sublime.DRAW_NO_OUTLINE
    view.add_regions(KEY_ADDED,   safe(added_lines),   "compare.added",   "dot",      flags)
    view.add_regions(KEY_DELETED, safe(deleted_lines), "compare.deleted", "dot",      flags)
    view.add_regions(KEY_CHANGED, safe(changed_lines), "compare.changed", "bookmark", flags)
    view.add_regions(KEY_BLANK,   safe(blank_lines),   "compare.blank",   "",         flags)


def _apply_inline_highlights(left_view, right_view, changed_pairs):
    left_regs  = _line_regions(left_view)
    right_regs = _line_regions(right_view)
    left_total  = len(left_regs)
    right_total = len(right_regs)

    left_inline  = []
    right_inline = []

    for (li, ri, ltext, rtext) in changed_pairs:
        if li >= left_total or ri >= right_total:
            continue
        l_line_start = left_regs[li].begin()
        r_line_start = right_regs[ri].begin()

        matcher = difflib.SequenceMatcher(None, ltext, rtext, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            if i1 < i2:
                left_inline.append(sublime.Region(l_line_start + i1, l_line_start + i2))
            if j1 < j2:
                right_inline.append(sublime.Region(r_line_start + j1, r_line_start + j2))

    flags = sublime.DRAW_NO_OUTLINE
    left_view.add_regions(KEY_INLINE,  left_inline,  "compare.inline", "", flags)
    right_view.add_regions(KEY_INLINE, right_inline, "compare.inline", "", flags)


def _apply_view_color_scheme(view):
    import os
    fname    = "ComparePlugin.tmTheme"
    fpath    = os.path.join(sublime.packages_path(), "User", fname)
    pkg_path = "Packages/User/" + fname
    BG = "#1D1F21"
    FG = "#D4D4D4"

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0">',
        '<dict>',
        '   <key>name</key><string>ComparePlugin</string>',
        '   <key>settings</key>',
        '   <array>',
        '       <dict>',
        '           <key>settings</key>',
        '           <dict>',
        '               <key>background</key><string>' + BG + '</string>',
        '               <key>foreground</key><string>' + FG + '</string>',
        '               <key>caret</key><string>#AEAFAD</string>',
        '               <key>lineHighlight</key><string>#2A2A2A</string>',
        '               <key>selection</key><string>#264F78</string>',
        '           </dict>',
        '       </dict>',
    ]

    def scope_entry(name, scope, bg, fg):
        return [
            '       <dict>',
            '           <key>name</key><string>' + name + '</string>',
            '           <key>scope</key><string>' + scope + '</string>',
            '           <key>settings</key>',
            '           <dict>',
            '               <key>background</key><string>' + bg + '</string>',
            '               <key>foreground</key><string>' + fg + '</string>',
            '           </dict>',
            '       </dict>',
        ]

    lines += scope_entry("Compare Added",   "compare.added",   COLOR_ADDED,   COLOR_ADDED_FG)
    lines += scope_entry("Compare Deleted", "compare.deleted", COLOR_DELETED, COLOR_DELETED_FG)
    lines += scope_entry("Compare Changed", "compare.changed", COLOR_CHANGED, COLOR_CHANGED_FG)
    lines += scope_entry("Compare Blank",   "compare.blank",   COLOR_BLANK,   COLOR_BLANK_FG)
    lines += scope_entry("Compare Inline",  "compare.inline",  COLOR_INLINE,  "#000000")
    lines += [' </array>', '</dict>', '</plist>']

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
        self.left_lines    = []
        self.right_lines   = []
        self.left_marks    = {"added": [], "deleted": [], "changed": [], "blank": []}
        self.right_marks   = {"added": [], "deleted": [], "changed": [], "blank": []}
        self.diff_blocks   = []
        self.changed_pairs = []


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
                li += 1; ri += 1
        elif tag == "insert":
            result.diff_blocks.append((li, ri))
            for k in range(j2 - j1):
                l_out.append(BLANK_FILL)
                r_out.append(right_lines[j1 + k])
                l_blank.append(li); r_added.append(ri)
                li += 1; ri += 1
        elif tag == "delete":
            result.diff_blocks.append((li, ri))
            for k in range(i2 - i1):
                l_out.append(left_lines[i1 + k])
                r_out.append(BLANK_FILL)
                l_deleted.append(li); r_blank.append(ri)
                li += 1; ri += 1
        elif tag == "replace":
            result.diff_blocks.append((li, ri))
            lcount = i2 - i1
            rcount = j2 - j1
            for k in range(max(lcount, rcount)):
                lline = left_lines[i1 + k]  if k < lcount else BLANK_FILL
                rline = right_lines[j1 + k] if k < rcount else BLANK_FILL
                l_out.append(lline); r_out.append(rline)
                if k < lcount and k < rcount:
                    l_changed.append(li); r_changed.append(ri)
                    result.changed_pairs.append((li, ri, lline, rline))
                elif k < lcount:
                    l_deleted.append(li); r_blank.append(ri)
                else:
                    l_blank.append(li); r_added.append(ri)
                li += 1; ri += 1

    result.left_lines  = l_out
    result.right_lines = r_out
    result.left_marks  = {"added": l_added, "deleted": l_deleted,
                          "changed": l_changed, "blank": l_blank}
    result.right_marks = {"added": r_added, "deleted": r_deleted,
                          "changed": r_changed, "blank": r_blank}
    return result


# ──────────────────────────────────────────────────────────────
#  Session
# ──────────────────────────────────────────────────────────────

class CompareSession(object):
    def __init__(self, source_window, compare_window, left_display, right_display, diff):
        self.source_window = source_window
        self.window        = compare_window
        self.left_display  = left_display
        self.right_display = right_display
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
#  Core runner — defers all work until new_window is ready
# ──────────────────────────────────────────────────────────────

def run_compare(source_window, left_source, right_source):
    _close_session_by_source(source_window.id())

    diff     = compute_diff(_get_lines(left_source), _get_lines(right_source))
    left_id  = left_source.id()
    right_id = right_source.id()
    before_ids = set(w.id() for w in sublime.windows())

    sublime.run_command("new_window")

    def on_window_ready():
        compare_window = None
        for w in sublime.windows():
            if w.id() not in before_ids:
                compare_window = w
                break
        if compare_window is None:
            print("ComparePlugin: new_window not found, aborting")
            return

        left_source_view  = None
        right_source_view = None
        for v in source_window.views():
            if v.id() == left_id:
                left_source_view = v
            if v.id() == right_id:
                right_source_view = v

        if not left_source_view or not right_source_view:
            print("ComparePlugin: source views lost after new_window")
            return

        _finish_compare(source_window, compare_window, left_source_view, right_source_view, diff)

    sublime.set_timeout(on_window_ready, 100)


def _finish_compare(source_window, compare_window, left_source, right_source, diff):
    def display_name(view):
        fname = view.file_name()
        if fname:
            name = fname.replace("\\", "/").split("/")[-1]
        else:
            name = view.name() or "untitled"
        return "[Compare] " + name

    left_display  = compare_window.new_file()
    right_display = compare_window.new_file()

    left_display.set_scratch(True)
    right_display.set_scratch(True)
    left_display.set_read_only(True)
    right_display.set_read_only(True)
    left_display.set_name(display_name(left_source))
    right_display.set_name(display_name(right_source))

    left_syntax  = left_source.settings().get("syntax")
    right_syntax = right_source.settings().get("syntax")
    if left_syntax:
        left_display.set_syntax_file(left_syntax)
    if right_syntax:
        right_display.set_syntax_file(right_syntax)

    for dv in (left_display, right_display):
        dv.settings().set("minimap", True)
        dv.settings().set("word_wrap", False)

    compare_window.set_layout({
        "cols":  [0.0, 0.5, 1.0],
        "rows":  [0.0, 1.0],
        "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]
    })

    # Close only the blank untitled view new_window creates — never file-backed views
    for v in compare_window.views():
        if v.id() not in (left_display.id(), right_display.id()):
            if v.file_name() is None and not v.is_dirty():
                v.set_scratch(True)
                v.close()

    compare_window.set_view_index(left_display,  0, 0)
    compare_window.set_view_index(right_display, 1, 0)

    left_display.set_read_only(False)
    right_display.set_read_only(False)
    _set_view_content(left_display,  "\n".join(diff.left_lines))
    _set_view_content(right_display, "\n".join(diff.right_lines))
    left_display.set_read_only(True)
    right_display.set_read_only(True)

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
    session = _sessions.pop(window_id, None)
    if not session:
        return
    _sessions.pop(session.source_window.id(), None)
    _sessions.pop(session.window.id(), None)

    if close_views:
        for v in (session.left_display, session.right_display):
            try:
                v.set_read_only(False)
                v.set_scratch(True)
                v.close()
            except Exception:
                pass


def _close_session_by_source(source_window_id):
    _close_session(source_window_id, close_views=True)


# ──────────────────────────────────────────────────────────────
#  Internal text command
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

        self.window.show_quick_panel(
            self._names,
            self._on_first,
            placeholder="Compare: select the 1st file"
        )

    def _on_first(self, idx):
        if idx == -1:
            return
        self._selected.append(idx)

        active_ids = set()
        session = _sessions.get(self.window.id())
        if session:
            active_ids = set(session.display_view_ids())
        self._views = [v for v in self.window.views() if v.id() not in active_ids]
        self._names = [
            v.file_name() or v.name() or ("<untitled " + str(v.id()) + ">")
            for v in self._views
        ]

        first_name = (
            self._views[self._selected[0]].file_name() or
            self._views[self._selected[0]].name() or
            "<untitled " + str(self._views[self._selected[0]].id()) + ">"
        ) if self._selected[0] < len(self._views) else ""

        self.window.show_quick_panel(
            self._names,
            self._on_second,
            placeholder="Compare: select the 2nd file (first: " + first_name.split("/")[-1].split("\\")[-1] + ")"
        )

    def _on_second(self, idx):
        if idx == -1:
            return
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
        saved_view = self.window.new_file()
        saved_view.set_scratch(True)
        saved_view.set_name("[Saved] " + fname.replace("\\", "/").split("/")[-1])
        _set_view_content(saved_view, saved)
        run_compare(self.window, saved_view, view)
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
# ──────────────────────────────────────────────────────────────

class CompareCloseListener(sublime_plugin.EventListener):

    def on_pre_close_window(self, window):
        session = _sessions.get(window.id())
        if session and window.id() == session.window.id():
            _sessions.pop(session.source_window.id(), None)
            _sessions.pop(session.window.id(), None)

    def on_pre_close(self, view):
        seen = set()
        for wid, session in list(_sessions.items()):
            if session.window.id() in seen:
                continue
            if view.id() in session.display_view_ids():
                seen.add(session.window.id())
                _sessions.pop(session.source_window.id(), None)
                _sessions.pop(session.window.id(), None)
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
    pass


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

        l_prev  = _last_vp.get(lv.id())
        r_prev  = _last_vp.get(rv.id())
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
# ──────────────────────────────────────────────────────────────

import os
import json

_SCHEME_FILENAME = "ComparePlugin.sublime-color-scheme"


def _scheme_path():
    return os.path.join(sublime.packages_path(), "User", _SCHEME_FILENAME)


def _install_color_scheme():
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
    _poll_active = False
    _install_color_scheme()
    import sys
    print("ComparePlugin loaded OK (Python " + sys.version + ")")


def plugin_unloaded():
    global _poll_active
    _poll_active = False
    for wid in list(_sessions.keys()):
        _close_session(wid, close_views=True)
    _sessions.clear()
    _last_vp.clear()
    _syncing.clear()
    _remove_color_scheme()
