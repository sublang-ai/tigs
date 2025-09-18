"""Text utility functions for TUI components."""

import os
import sys
from typing import List, Iterable
from wcwidth import wcswidth


def display_width(text: str) -> int:
    """Calculate the display width of text accounting for Unicode, emoji, etc.
    
    Args:
        text: Text to measure
        
    Returns:
        Display width in terminal columns
    """
    if not text:
        return 0
    w = wcswidth(text)
    # wcswidth can return -1 on unprintables; treat as 0 columns so we don't go negative
    return max(w, 0) if w is not None else 0


def _break_token(token: str, width: int) -> Iterable[str]:
    """Break a single token into chunks that each fit into 'width' by display width."""
    if width <= 0:
        yield token
        return
    out = []
    acc = 0
    buf = []
    for ch in token:
        w = display_width(ch)
        if acc + w <= width:
            buf.append(ch)
            acc += w
        else:
            # flush
            out.append(''.join(buf))
            buf = [ch]
            acc = w
    if buf:
        out.append(''.join(buf))
    for part in out:
        yield part


def word_wrap(text: str, width: int) -> List[str]:
    """Word wrap text to specified width using display width (Unicode-aware).
    Breaks long tokens as needed so no line exceeds the width."""
    if width <= 0:
        return [text if text is not None else ""]
    if text is None:
        return [None]
    if not text:
        return [""]
    if display_width(text) <= width:
        return [text]

    words = text.split()
    if not words:  # all whitespace
        return [""]

    lines: List[str] = []
    line: str = ""
    line_w: int = 0

    for word in words:
        ww = display_width(word)
        space_w = 1 if line else 0  # assume single-column space
        if line and line_w + space_w + ww <= width:
            line += " " + word
            line_w += space_w + ww
            continue
        if not line and ww <= width:
            line = word
            line_w = ww
            continue

        # Need to wrap: first flush current line if it has content
        if line:
            lines.append(line)
            line, line_w = "", 0

        # Break this token into width-sized pieces
        parts = list(_break_token(word, width))
        # All full-width parts except the last are complete lines
        for part in parts[:-1]:
            lines.append(part)
        last = parts[-1] if parts else ""
        # Start the next line with remainder (may be empty)
        line, line_w = last, display_width(last)

    if line or not lines:
        lines.append(line)
    return lines


def truncate_with_ellipsis(text: str, width: int, ellipsis: str = "...") -> str:
    """Truncate by display width, appending an ellipsis if needed."""
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    ell_w = display_width(ellipsis)
    if width <= ell_w:
        # Degenerate case: return as much of the ellipsis as fits
        return ellipsis[:1] if width == 1 else ""
    target = width - ell_w
    out_chars = []
    acc = 0
    for ch in text:
        w = display_width(ch)
        if acc + w > target:
            break
        acc += w
        out_chars.append(ch)
    return "".join(out_chars) + ellipsis


def is_iterm2() -> bool:
    """Check if running in iTerm2."""
    return os.environ.get('TERM_PROGRAM') == 'iTerm.app'


def clear_iterm2_scrollback() -> None:
    """Clear iTerm2 scrollback buffer."""
    if is_iterm2():
        sys.stdout.write('\033[2J\033[H\033[3J')
        sys.stdout.flush()