"""Main TUI application for tigs store command."""

import curses
import os
import sys
from datetime import datetime, timedelta
from typing import List

from cligent import ChatParser

from .commits_view import CommitView
from .messages_view import MessageView
from .logs_view import LogsView
from .layout_manager import LayoutManager
from .pane_renderer import PaneRenderer
from .text_utils import clear_iterm2_scrollback


class TigsStoreApp:
    """Main TUI application for selecting and storing commits/messages."""
    
    MIN_WIDTH = 80
    MIN_HEIGHT = 24
    
    def __init__(self, store):
        """Initialize the TUI application.
        
        Args:
            store: TigsStore instance for Git operations
        """
        self.store = store
        self.focused_pane = 0  # 0=commits, 1=messages, 2=logs
        self.running = True
        self.status_message = ""  # Status message to display
        self.status_message_time = None  # When status was set
        self._colors_enabled = False  # Track if colors were successfully initialized
        
        # Initialize chat parser
        try:
            self.chat_parser = ChatParser('claude-code')
        except Exception:
            # Handle cligent initialization errors gracefully
            self.chat_parser = None
        
        # Initialize layout manager
        self.layout_manager = LayoutManager()
        
        # Initialize view components
        self.commit_view = CommitView(self.store)
        self.message_view = MessageView(self.chat_parser)
        self.log_view = LogsView(self.chat_parser)
        
        # Give layout manager to commit view for horizontal scrolling
        self.commit_view.layout_manager = self.layout_manager
        
        # Load initial data
        if self.chat_parser:
            self.log_view.load_logs()
            # Auto-load messages for the first log
            log_id = self.log_view.get_selected_log_id()
            if log_id:
                self.message_view.load_messages(log_id)
        
    def run(self) -> None:
        """Run the TUI application."""
        try:
            curses.wrapper(self._run)
        except KeyboardInterrupt:
            pass  # Exit gracefully on Ctrl+C
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    
    def _run(self, stdscr) -> None:
        """Main TUI loop.
        
        Args:
            stdscr: The curses standard screen
        """
        # Set up curses
        try:
            curses.curs_set(0)  # Hide cursor
        except curses.error:
            pass  # Some terminals don't support hiding cursor
        stdscr.keypad(True)  # Enable special keys
        curses.noecho()
        
        # Initialize colors if available
        self._colors_enabled = False
        if curses.has_colors() and not self._no_color():
            try:
                curses.start_color()
                try:
                    curses.use_default_colors()
                    use_default_ok = True
                except curses.error:
                    use_default_ok = False

                if use_default_ok:
                    curses.init_pair(1, -1, -1)
                else:
                    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
                
                # Color pairs matching tig's scheme:
                curses.init_pair(2, curses.COLOR_CYAN, -1 if use_default_ok else curses.COLOR_BLACK)     # Author, focused border
                curses.init_pair(3, curses.COLOR_GREEN, -1 if use_default_ok else curses.COLOR_BLACK)    # Commit SHA, additions
                curses.init_pair(4, curses.COLOR_YELLOW, -1 if use_default_ok else curses.COLOR_BLACK)   # Date, headers
                curses.init_pair(5, curses.COLOR_MAGENTA, -1 if use_default_ok else curses.COLOR_BLACK)  # Refs, diff chunks
                curses.init_pair(6, curses.COLOR_RED, -1 if use_default_ok else curses.COLOR_BLACK)      # Deletions
                curses.init_pair(7, curses.COLOR_BLUE, -1 if use_default_ok else curses.COLOR_BLACK)     # Other metadata

                self._colors_enabled = True
            except curses.error:
                # leave colors off gracefully
                self._colors_enabled = False
        
        # Main loop
        while self.running:
            height, width = stdscr.getmaxyx()
            
            # Check minimum size
            if width < self.MIN_WIDTH or height < self.MIN_HEIGHT:
                # Don't exit, just show message and wait
                stdscr.clear()
                
                # Show size warning
                try:
                    stdscr.addstr(0, 0, f"Terminal too small!")
                    stdscr.addstr(2, 0, f"Required: {self.MIN_WIDTH}x{self.MIN_HEIGHT}")
                    stdscr.addstr(3, 0, f"Current:  {width}x{height}")
                    stdscr.addstr(5, 0, "Please resize terminal")
                    stdscr.addstr(6, 0, "or press 'q' to quit")
                except curses.error:
                    # Terminal is really small, just show what we can
                    try:
                        stdscr.addstr(0, 0, f"Resize: {self.MIN_WIDTH}x{self.MIN_HEIGHT}")
                    except:
                        pass
                
                stdscr.refresh()
                
                # Handle input while too small
                stdscr.timeout(100)  # Non-blocking with 100ms timeout
                key = stdscr.getch()
                
                if key == ord('q') or key == ord('Q'):
                    self.running = False
                elif key == curses.KEY_RESIZE:
                    # Terminal was resized, loop will check size again
                    pass
                    
                continue  # Skip normal drawing, check size again
            
            # Reset to blocking input for normal operation
            stdscr.timeout(-1)
            
            # Clear iTerm2 scrollback buffer + standard curses clear
            clear_iterm2_scrollback()
            stdscr.clear()
            
            # Calculate pane dimensions
            pane_height = height - 1  # Reserve bottom for status bar
            
            # Get commit titles for width calculation
            commit_titles = [c['subject'] for c in self.commit_view.commits]
            log_count = len(self.log_view.logs) if self.log_view.logs else 0
            
            # Calculate dynamic widths
            if self.layout_manager.needs_recalculation(width):
                commit_width, message_width, log_width = self.layout_manager.calculate_column_widths(
                    width, commit_titles, log_count, read_only_mode=False  # Full prefix with checkboxes
                )
            else:
                commit_width, message_width, log_width = self.layout_manager.cached_widths
            
            # Handle no logs case - give extra space to messages
            if log_count == 0:
                message_width = width - commit_width
                log_pane_width = 0
            else:
                log_pane_width = log_width
            
            # Get commit display lines (now with width and colors parameters)
            commit_lines = self.commit_view.get_display_lines(pane_height, commit_width, self._colors_enabled)
            
            # DEBUG: Add status to see if commits are loading
            if not commit_lines:
                commit_lines = [f"DEBUG: {len(self.commit_view.commits)} commits"]
            
            # Draw panes using PaneRenderer
            PaneRenderer.draw_pane(stdscr, 0, 0, pane_height, commit_width, 
                                  "Commits", self.focused_pane == 0,
                                  commit_lines, self._colors_enabled)
            
            # Get message display lines (now with width and colors parameters)
            message_lines = self.message_view.get_display_lines(pane_height, message_width, self._colors_enabled)
            
            PaneRenderer.draw_pane(stdscr, 0, commit_width, pane_height, message_width,
                                  "Messages", self.focused_pane == 1,
                                  message_lines, self._colors_enabled)
            
            # Get log display lines and draw logs pane only if wide enough
            if log_pane_width >= 2:
                log_lines = self.log_view.get_display_lines(pane_height)
                PaneRenderer.draw_pane(stdscr, 0, commit_width + message_width, pane_height, log_pane_width,
                                      "Logs", self.focused_pane == 2,
                                      log_lines, self._colors_enabled)
            
            # Draw status bar
            self._draw_status_bar(stdscr, height - 1, width)
            
            # Refresh to show everything
            stdscr.refresh()
            
            # Handle input
            key = stdscr.getch()
            if key == ord('q') or key == ord('Q'):
                self.running = False
            elif key == ord('\n') or key == 10:  # Enter key
                self._handle_store_operation(stdscr)
            elif key == ord('\t'):  # Tab
                self.focused_pane = (self.focused_pane + 1) % 3
            elif key == curses.KEY_BTAB or key == 353:  # Shift-Tab
                self.focused_pane = (self.focused_pane - 1) % 3
            elif key == curses.KEY_RESIZE:
                self._handle_resize(stdscr)
                continue  # Redraw with new dimensions
            elif self.focused_pane == 0:  # Commits pane focused
                self.commit_view.handle_input(key, pane_height)
            elif self.focused_pane == 1:  # Messages pane focused
                self.message_view.handle_input(stdscr, key, pane_height)
            elif self.focused_pane == 2:  # Logs pane focused
                if self.log_view.handle_input(key):
                    # Log selection changed, reload messages
                    log_id = self.log_view.get_selected_log_id()
                    if log_id:
                        self.message_view.load_messages(log_id)
    def _draw_status_bar(self, stdscr, y: int, width: int) -> None:
        """Draw the status bar.
        
        Args:
            stdscr: The curses screen
            y: Y position for status bar
            width: Width of screen
        """
        # Show status message if recent (within 5 seconds)
        if self.status_message and self.status_message_time:
            elapsed = datetime.now() - self.status_message_time
            if elapsed < timedelta(seconds=5):
                status_text = self.status_message
            else:
                self.status_message = ""  # Clear old message
                status_text = "Tab: switch | Enter: store | q: quit"
        else:
            status_text = "Tab: switch | Enter: store | q: quit"
        
        # Add size warning if getting close to minimum
        height = stdscr.getmaxyx()[0]
        if width < self.MIN_WIDTH + 10 or height < self.MIN_HEIGHT + 5:
            status_text += f" | Size: {width}x{height} (min: {self.MIN_WIDTH}x{self.MIN_HEIGHT})"
        
        # Use reverse video for status bar (honor NO_COLOR)
        if self._colors_enabled:
            stdscr.attron(curses.A_REVERSE)
        
        # Clear the line and add status text
        status_line = status_text.ljust(width)[:width - 1]
        try:
            stdscr.addstr(y, 0, status_line)
        except curses.error:
            pass
            
        if self._colors_enabled:
            stdscr.attroff(curses.A_REVERSE)
    
    def _handle_store_operation(self, stdscr) -> None:
        """Handle the store operation when Enter is pressed.
        
        Args:
            stdscr: The curses screen for prompts
        """
        # Get selected commits
        selected_commits = self.commit_view.get_selected_shas()
        
        # Validate that both commits and messages are selected
        if not selected_commits:
            self.status_message = "Error: No commits selected"
            self.status_message_time = datetime.now()
            return
        
        if not self.message_view.selected_messages:
            self.status_message = "Error: No messages selected"
            self.status_message_time = datetime.now()
            return
        
        # Get the content in cligent's export format
        chat_content = self.message_view.get_selected_messages_content()
        num_messages = len(self.message_view.selected_messages)
        
        # Store to each selected commit
        stored_count = 0
        overwrite_count = 0
        errors = []
        
        for sha in selected_commits:
            try:
                # Try to add the chat
                self.store.add_chat(sha, chat_content)
                stored_count += 1
            except ValueError as e:
                if "already has a chat" in str(e):
                    # Offer to overwrite
                    if self._prompt_overwrite(stdscr, sha):
                        try:
                            # Remove existing and add new
                            self.store.remove_chat(sha)
                            self.store.add_chat(sha, chat_content)
                            stored_count += 1
                            overwrite_count += 1
                        except Exception as ex:
                            errors.append(f"{sha[:7]}: {str(ex)}")
                else:
                    errors.append(f"{sha[:7]}: {str(e)}")
        
        # Update status message
        if errors:
            self.status_message = f"Errors: {'; '.join(errors)}"
        else:
            msg = f"Stored {num_messages} messages → {stored_count} commits"
            if overwrite_count > 0:
                msg += f" ({overwrite_count} overwritten)"
            self.status_message = msg
        
        self.status_message_time = datetime.now()
        
        # Clear selections after successful storage
        if stored_count > 0:
            self.commit_view.clear_selection()
            self.message_view.clear_selection()
            
            # Update commit indicators (reload to get updated notes status)
            self.commit_view.load_commits()
    
    def _prompt_overwrite(self, stdscr, sha: str) -> bool:
        """Prompt user to overwrite existing note.
        
        Args:
            stdscr: The curses screen
            sha: The commit SHA
            
        Returns:
            True if user wants to overwrite
        """
        # Simple implementation - always overwrite for now
        # Could be enhanced with actual prompt dialog
        return True
    
    def _handle_resize(self, stdscr) -> None:
        """Handle terminal resize event.
        
        Args:
            stdscr: The curses screen
        """
        # Clear and refresh to get new dimensions
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        
        # Force recalculation of column widths
        self.layout_manager.cached_widths = None
        
        # Reset message view to recalculate heights
        self.message_view._needs_message_view_init = True
        
        # Ensure cursors are visible
        pane_height = height - 1
        self.commit_view.scroll_to_cursor(pane_height)
        self.message_view.scroll_to_cursor(pane_height)
    
    def _no_color(self) -> bool:
        """Check if colors should be disabled via NO_COLOR environment variable.
        
        Returns:
            True if NO_COLOR is set and non-empty
        """
        return bool(os.environ.get('NO_COLOR', '').strip())