#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: The class tables checks/mcp_ide.py judges an IDE MCP server's tools by — pure data plus
#          one lookup function, no imports beyond the standard library's typing, deliberately kept
#          apart from mcp_ide.py itself: dispatch.py's fail-closed fallback (_mcp_call_needs_mcp_ide)
#          must judge a call by the very same tables whether mcp_ide.py raised while running or
#          could not be imported at all (review, 2026-09-26, finding LOW: the two failure
#          modes used to judge the same orchestrator `create_new_file` differently — exit 2 after a
#          runtime error, 0 after an import error). A module with nothing to fail on is the one thing
#          both paths can still share.
#
#          Four classes, by the tool's own name (the suffix of `mcp__<server>__<tool>`):
#            - shell: one string argument is a command line (`execute_terminal_command`).
#            - write: the tool names the file(s) it changes — see _WRITE_TOOL_FIELDS for each one's
#                     real schema (JetBrains `idea` MCP server, live session 2026-09-26; the
#                     `replace_text_in_file` entry from the 2025.x server per a review,
#                     finding M-b: `pathInProject` plus the old/new text).
#            - exec:  runs something with no argument any check could evaluate as a path or a
#                     command line (`execute_run_configuration`, `build_project`, `xdebug_*`, ...,
#                     and Claude Code's own `mcp__ide__executeCode`, finding M-a).
#            - read:  plainly read-only. An **exact** list, not name prefixes (finding M-b: a prefix
#                     rule read `find_and_replace` as a read because it starts with `find_`, and let a
#                     worker run it) — every read tool of the JetBrains server enumerated in
#                     `tests/probes/t76-d3/jetbrains_tools.txt` of the template-maintenance repo,
#                     plus `getDiagnostics` from Claude Code's own `ide` server.
#          A tool of an IDE server in none of the four is "unlisted": denied for a worker, noted for
#          the orchestrator — see mcp_ide.check_mcp_ide. `_tool_class` is the one lookup both
#          modules use, so the two can never disagree on a name.

from __future__ import annotations

from typing import Optional

__all__ = [
    "_SHELL_TOOL_ARGS", "_WRITE_TOOL_FIELDS", "_EXEC_TOOLS", "_READ_TOOLS", "_tool_class",
]

# suffix -> the tool_input field(s) holding its command line, first present non-empty string wins.
_SHELL_TOOL_ARGS = {
    "execute_terminal_command": ("command",),
}

# suffix -> how to read its write target(s) out of tool_input.
#   "kind": "single" -- one path, first of "fields" present as a non-empty string.
#   "kind": "list"   -- "fields"[0] is a list of path strings, every non-empty one is a target.
#   "kind": "patch"  -- first of "fields" present as a non-empty string is patch *text*; its
#                        targets are the paths mcp_ide._patch_paths finds inside that text.
# "project_wide": True marks rename_refactoring's own special case -- see mcp_ide.py's docstring
# and mcp_ide._rename_worker_scope.
_WRITE_TOOL_FIELDS = {
    "apply_patch": {"kind": "patch", "fields": ("input", "patch")},
    "create_new_file": {"kind": "single", "fields": ("pathInProject",)},
    "create_notebook": {"kind": "single", "fields": ("pathInProject",)},
    "reformat_file": {"kind": "list", "fields": ("files",)},
    "rename_refactoring": {"kind": "single", "fields": ("pathInProject",), "project_wide": True},
    "replace_text_in_file": {"kind": "single", "fields": ("pathInProject", "filePath", "file_path")},
    "apply_quick_fix": {"kind": "single", "fields": ("filePath",)},
    "edit_notebook": {"kind": "single", "fields": ("file_path",)},
}

# Tools with no argument any existing check could evaluate as a path or command line. See
# mcp_ide.py's docstring for why cancel_sql_query/interrupt_notebook/kill_notebook/
# test_database_connection/xdebug_set_breakpoint/xdebug_remove_breakpoint are deliberately here
# (review finding 3), not an oversight.
_EXEC_TOOLS = frozenset({
    "execute_run_configuration",
    "execute_code_on_kernel",
    "run_notebook_cell",
    "execute_tool",
    "invoke_ide_action",
    "build_project",
    "execute_sql_query",
    "create_database_connection",
    "edit_database_connection",
    "configure_python_interpreter",
    "cancel_sql_query",
    "interrupt_notebook",
    "kill_notebook",
    "test_database_connection",
    "xdebug_set_variable",
    "xdebug_control_session",
    "xdebug_evaluate_expression",
    "xdebug_remove_breakpoint",
    "xdebug_run_to_line",
    "xdebug_set_breakpoint",
    "xdebug_start_debugger_session",
    "executeCode",  # Claude Code's own `ide` server: runs code in the IDE's Jupyter kernel
})

# Plainly read-only tools, by exact name (never by prefix -- see this module's header).
_READ_TOOLS = frozenset({
    # JetBrains `idea` MCP server
    "analyze_calls",
    "fetch_query_result",
    "get_all_open_file_paths",
    "get_composer_dependencies",
    "get_database_object_description",
    "get_file_problems",
    "get_inspections",
    "get_notebook_state",
    "get_php_project_config",
    "get_project_dependencies",
    "get_project_modules",
    "get_python_environment",
    "get_repositories",
    "get_run_configurations",
    "get_structural_patterns",
    "get_symbol_info",
    "git_status",
    "introspect_schema",
    "lint_files",
    "list_database_connections",
    "list_database_schemas",
    "list_directory_tree",
    "list_recent_sql_queries",
    "list_schema_object_kinds",
    "list_schema_objects",
    "open_file_in_editor",
    "preview_table_data",
    "read_file",
    "read_notebook",
    "read_notebook_cell",
    "search_file",
    "search_ide_actions",
    "search_regex",
    "search_structural",
    "search_symbol",
    "search_text",
    "wait_cell_execution",
    "xdebug_get_debugger_status",
    "xdebug_get_frame_values",
    "xdebug_get_stack",
    "xdebug_get_threads",
    "xdebug_get_value_by_path",
    "xdebug_list_breakpoints",
    # Claude Code's own `ide` server
    "getDiagnostics",
})


def _tool_class(suffix: str) -> Optional[str]:
    """"shell", "write", "exec" or "read" for a tool name one of the tables above lists; None for
    an unlisted one. Checked in that order, so a name listed twice by mistake would still get one
    answer -- the probe that pins these tables (t76-d3) asserts no name is."""
    if suffix in _SHELL_TOOL_ARGS:
        return "shell"
    if suffix in _WRITE_TOOL_FIELDS:
        return "write"
    if suffix in _EXEC_TOOLS:
        return "exec"
    if suffix in _READ_TOOLS:
        return "read"
    return None
