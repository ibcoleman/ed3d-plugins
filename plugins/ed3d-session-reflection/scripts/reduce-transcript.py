#!/usr/bin/env python3
# pattern: Mixed (unavoidable)
# Reason: CLI entry point — parses args, reads JSONL, writes output.
# Pure transformation logic is separated into functions below.
"""
Reduce a Claude Code JSONL transcript to a token-efficient text format
suitable for LLM analysis.

Usage:
    python3 reduce-transcript.py <input.jsonl> [output.txt]
    python3 reduce-transcript.py <input.jsonl>  # writes to stdout

Strips metadata (UUIDs, permissionMode, version, gitBranch, etc.)
and retains: role, message content, tool names, tool inputs, tool results,
and timestamps.
"""

import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Functional Core — pure transformation, no I/O
# ---------------------------------------------------------------------------

# JSONL line types we care about
MESSAGE_TYPES = {"user", "assistant", "tool_use", "tool_result"}

# Metadata fields to drop entirely
SKIP_TYPES = {"file-history-snapshot", "queue-operation", "progress"}


def extract_text_from_content(content):
    """Extract human-readable text from a message content field.

    Content can be a string or a list of content blocks.
    """
    if isinstance(content, str):
        return content

    if not isinstance(content, list):
        return ""

    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type", "")

        if block_type == "text":
            text = block.get("text", "")
            if text.strip():
                parts.append(text)

        elif block_type == "tool_use":
            tool_name = block.get("name", "unknown")
            tool_input = block.get("input", {})
            input_summary = _summarize_tool_input(tool_input)
            parts.append(f"[tool_use:{tool_name}] {input_summary}")

        elif block_type == "tool_result":
            tool_id = block.get("tool_use_id", "")
            result_content = block.get("content", "")
            result_text = extract_text_from_content(result_content)
            if result_text.strip():
                parts.append(f"[tool_result] {_truncate(result_text, 2000)}")

        elif block_type == "thinking":
            # Include thinking blocks — they reveal agent reasoning
            text = block.get("thinking", "")
            if text.strip():
                parts.append(f"[thinking] {_truncate(text, 1000)}")

    return "\n".join(parts)


def _summarize_tool_input(tool_input):
    """Produce a concise summary of tool input."""
    if isinstance(tool_input, str):
        return _truncate(tool_input, 500)

    if not isinstance(tool_input, dict):
        return str(tool_input)[:500]

    # For common tools, show the most relevant field concisely
    parts = []
    for key, value in tool_input.items():
        if isinstance(value, str) and len(value) > 200:
            parts.append(f"{key}: {_truncate(value, 200)}")
        else:
            parts.append(f"{key}: {value}")

    return "; ".join(parts)


def _truncate(text, max_len):
    """Truncate text with ellipsis indicator."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "...[truncated]"


def reduce_line(line_data):
    """Reduce a single parsed JSONL line to a formatted string, or None to skip."""
    line_type = line_data.get("type", "")

    if line_type in SKIP_TYPES:
        return None

    # Handle direct message types (user, assistant)
    if line_type in ("user", "assistant"):
        message = line_data.get("message", {})
        role = message.get("role", line_type)
        content = message.get("content", "")
        text = extract_text_from_content(content)
        if not text.strip():
            return None

        timestamp = line_data.get("timestamp", "")
        ts_prefix = f" ({timestamp})" if timestamp else ""
        return f"[{role}]{ts_prefix}\n{text}"

    # Handle tool_use and tool_result as standalone line types
    if line_type == "tool_use":
        tool_name = line_data.get("tool_name", line_data.get("name", "unknown"))
        tool_input = line_data.get("input", line_data.get("tool_input", {}))
        input_summary = _summarize_tool_input(tool_input)
        return f"[tool_use:{tool_name}]\n{input_summary}"

    if line_type == "tool_result":
        result = line_data.get("output", line_data.get("tool_response", ""))
        if isinstance(result, dict):
            result = json.dumps(result, indent=2)
        result_text = _truncate(str(result), 2000)
        if not result_text.strip():
            return None
        return f"[tool_result]\n{result_text}"

    # For any other type, check if there's a message with content
    message = line_data.get("message", {})
    if message and isinstance(message, dict):
        content = message.get("content", "")
        text = extract_text_from_content(content)
        if text.strip():
            role = message.get("role", line_type)
            return f"[{role}]\n{text}"

    return None


def reduce_transcript(lines):
    """Reduce a sequence of parsed JSONL objects to formatted text lines."""
    results = []
    for line_data in lines:
        reduced = reduce_line(line_data)
        if reduced:
            results.append(reduced)
    return results


# ---------------------------------------------------------------------------
# Imperative Shell — I/O only
# ---------------------------------------------------------------------------

def parse_jsonl_file(path):
    """Read a JSONL file and yield parsed JSON objects, skipping bad lines."""
    with open(path, "r", encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, 1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                yield json.loads(raw_line)
            except json.JSONDecodeError:
                # Skip corrupted lines silently
                pass


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input.jsonl> [output.txt]", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    lines = parse_jsonl_file(input_path)
    reduced = reduce_transcript(lines)
    output_text = "\n\n---\n\n".join(reduced)

    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text, encoding="utf-8")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
