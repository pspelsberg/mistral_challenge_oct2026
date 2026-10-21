"""PTY subprocess and virtual 80x24 ANSI screen buffer using pyte (Section 7)."""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import time
from pathlib import Path

import pyte


class PtyRogueProcess:
    """Manages a Rogue child process attached to a 80x24 POSIX pseudo-terminal."""

    def __init__(
        self,
        binary_path: Path,
        cols: int = 80,
        rows: int = 24,
        player_name: str = "LeChonk",
    ) -> None:
        self.binary_path = binary_path
        self.cols = cols
        self.rows = rows
        self.player_name = player_name

        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)

        self._master_fd: int | None = None
        self._proc: subprocess.Popen[bytes] | None = None

    @property
    def is_alive(self) -> bool:
        """Return True if the child Rogue process is currently running."""
        return self._proc is not None and self._proc.poll() is None

    def start(self, settle_timeout: float = 0.6) -> None:
        """Spawn the terminal Rogue binary inside a newly allocated 80x24 PTY."""
        self.close()
        if not self.binary_path.is_file():
            raise FileNotFoundError(
                f"Terminal Rogue binary not found at {self.binary_path}. "
                "Run './scripts/build_terminal_rogue.sh' first."
            )

        master_fd, slave_fd = pty.openpty()
        winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        env = os.environ.copy()
        # Use 'vt100' so ncurses never emits ECMA-48 REP (\x1b[nb) sequences unsupported by pyte
        env["TERM"] = "vt100"
        env["LINES"] = str(self.rows)
        env["COLUMNS"] = str(self.cols)
        env["ROGUEOPTS"] = f"name={self.player_name},Nopassgo"

        self.screen.reset()
        self._proc = subprocess.Popen(
            [str(self.binary_path.resolve())],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            cwd=str(self.binary_path.resolve().parent),
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave_fd)

        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self._master_fd = master_fd

        self.drain_output(max_wait=settle_timeout, quiet_window=0.08)

    def drain_output(self, max_wait: float = 0.35, quiet_window: float = 0.05) -> bytes:
        """Read available PTY output and feed it into the pyte screen buffer."""
        if self._master_fd is None:
            return b""

        collected = bytearray()
        deadline = time.monotonic() + max_wait
        received_any = False

        while time.monotonic() < deadline:
            timeout = quiet_window if received_any else min(0.1, max(0.01, deadline - time.monotonic()))
            ready, _, _ = select.select([self._master_fd], [], [], timeout)
            if not ready:
                if received_any:
                    break
                continue

            try:
                chunk = os.read(self._master_fd, 8192)
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.EBADF):
                    break
                if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    continue
                raise

            if not chunk:
                break

            received_any = True
            collected.extend(chunk)
            self.stream.feed(chunk)

        return bytes(collected)

    def send_keys(
        self,
        keys: list[str],
        inter_key_delay: float = 0.03,
        settle_timeout: float = 0.25,
    ) -> None:
        """Write a sequence of key tokens to the PTY and drain the updated screen."""
        if self._master_fd is None:
            raise RuntimeError("PTY process is not started.")

        for idx, key in enumerate(keys):
            raw = key.encode("utf-8", errors="ignore")
            os.write(self._master_fd, raw)
            if idx + 1 < len(keys):
                time.sleep(inter_key_delay)
                self.drain_output(max_wait=0.12, quiet_window=0.03)

        self.drain_output(max_wait=settle_timeout, quiet_window=0.05)

    def get_screen_lines(self) -> list[str]:
        """Return the reconstructed 24x80 terminal screen as a list of 24 strings."""
        return [line.rstrip() for line in self.screen.display]

    def get_cursor(self) -> tuple[int, int]:
        """Return (row, col) of the terminal cursor."""
        return (self.screen.cursor.y, self.screen.cursor.x)

    def close(self) -> None:
        """Cleanly terminate the PTY subprocess and release file descriptors."""
        if self._proc is not None:
            if self._proc.poll() is None:
                try:
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
                except OSError:
                    self._proc.terminate()
                try:
                    self._proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
                    except OSError:
                        self._proc.kill()
                    self._proc.wait(timeout=1.0)
            self._proc = None

        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
