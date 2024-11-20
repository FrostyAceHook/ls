import argparse
import os
import sys
from pathlib import Path
from dataclasses import dataclass





# interesting things about a node:
#   path
#   is directory?
#   size
#   for dir:
#     number of files
#     full contents
#   last modified time
#   creation time

@dataclass
class Entry:
    name: str = ""
    isdir: bool = False
    @property
    def path(self):
        return self.name + "/"*self.isdir

    _byte_size: int = None
    _subfiles: int = None
    _subdirs: int = None

    def _dir_process(self):
        if not self.isdir:
            raise ValueError("cannot dir process a file")
        # Process dirs, in a simple dfs.
        self._byte_size = 0
        self._subfiles = 0
        self._subdirs = 0
        stack = [self.name]
        while stack:
            try:
                it = os.scandir(stack.pop())
            except OSError:
                self._byte_size = -1
                self._subfiles = -1
                self._subdirs = -1
            else:
                with it:
                    for p in it:
                        if p.is_file():
                            self._subfiles += 1
                            self._byte_size += p.stat().st_size
                        else:
                            self._subdirs += 1
                            stack.append(p.path)

    @property
    def byte_size(self):
        if self._byte_size is None:
            self._dir_process()
        return self._byte_size
    @property
    def subfiles(self):
        if self._subfiles is None:
            self._dir_process()
        return self._subfiles
    @property
    def subdirs(self):
        if self._subdirs is None:
            self._dir_process()
        return self._subdirs


    def size(self, long=False):
        # short: "xxxU"
        # long:  "xxxxx UB"
        size = self.byte_size

        if size < 0:
            if long:
                return f" ???? ??"
            else:
                return f" ???"

        UNITS = ["k", "M", "G", "T", "P"]
        digits = 5 if (long) else 3

        if long and size <= 1024:
            return f"{size:>{digits}} B "

        size = float(size) / 1024
        unit = 0
        while size >= 1000 and unit < len(UNITS) - 1:
            size /= 1024
            unit += 1
        size = max(1.0, size)
        if long:
            units = f" {UNITS[unit]}B"
        else:
            units = f"{UNITS[unit]}"
        s = f"{size:.{digits}f}"
        s = s[:digits].rstrip(".")
        return f"{s:>{digits}}{units}"


    def sort_name(self):
        return (not self.isdir, self.name.casefold(), self.name)

    def sort_size(self):
        return (self.byte_size, *self.sort_name())


    @classmethod
    def create(cls, dir_entry):
        e = cls()
        e.name = dir_entry.name
        e.isdir = dir_entry.is_dir()

        # Process files now.
        if not e.isdir:
            e._byte_size = dir_entry.stat().st_size

        # Leave dir processing (since its expensive) for when they queried.
        return e



class cons:
    # hack to enable the control sequences.
    os.system("")

    @staticmethod
    def pos():
        # https://stackoverflow.com/a/69582478

        import sys
        import re
        is_windows = (sys.platform == "win32")
        if is_windows:
            import ctypes
            import ctypes.wintypes
        else:
            import termios

        if is_windows:
            old_stdin_mode = ctypes.wintypes.DWORD()
            old_stdout_mode = ctypes.wintypes.DWORD()
            kernel32 = ctypes.windll.kernel32
            stdin = kernel32.GetStdHandle(-10)
            stdout = kernel32.GetStdHandle(-11)
            kernel32.GetConsoleMode(stdin, ctypes.byref(old_stdin_mode))
            kernel32.SetConsoleMode(stdin, 0)
            kernel32.GetConsoleMode(stdout, ctypes.byref(old_stdout_mode))
            kernel32.SetConsoleMode(stdout, 7)
        else:
            old_stdin_mode = termios.tcgetattr(sys.stdin)
            attr = termios.tcgetattr(sys.stdin)
            attr[3] &= ~(termios.ECHO | termios.ICANON)
            termios.tcsetattr(sys.stdin, termios.TCSAFLUSH, attr)
        try:
            sys.stdout.write("\x1B[6n")
            sys.stdout.flush()
            response = ""
            while not response.endswith("R"):
                response += sys.stdin.read(1)
            match = re.match(r".*\[(\d+);(\d+)R", response)
        finally:
            if is_windows:
                kernel32.SetConsoleMode(stdin, old_stdin_mode)
                kernel32.SetConsoleMode(stdout, old_stdout_mode)
            else:
                termios.tcsetattr(sys.stdin, termios.TCSAFLUSH, old_stdin_mode)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return (-1, -1)

    @staticmethod
    def clear_line():
        sys.stdout.write("\x1B[2K\r")

    @staticmethod
    def move_up(by):
        if by <= 0:
            return 0
        y, _ = cons.pos()
        do = min(y - 1, by)
        sys.stdout.write(f"\x1B[{do}A")
        return do


class PRS:
    """ Print running sort. Items are printed in a sorted list, reprinting with
    every insertion. """

    def __init__(self, key, tostr, stream=None):
        self.key = key
        self.tostr = tostr
        self.items = None

    def __enter__(self):
        self.items = []
        return self

    def __exit__(self, etype, evalue, traceback):
        if etype is None:
            # If succeeded and we doing a running sort, then we gotta wipe the
            # printed output and reprint the full outupt.
            if self.key is not None:
                cons.move_up(len(self.items))
                for item in self.items:
                    cons.clear_line()
                    sys.stdout.write(self.tostr(item) + "\n")
                sys.stdout.flush()
        self.items = None
        return False

    def _bsearch(self, elem):
        # Binary search.
        left, right = 0, len(self.items)
        while left < right:
            mid = (left + right) // 2
            if self.key(self.items[mid]) < self.key(elem):
                left = mid + 1
            else:
                right = mid
        return left

    def insert(self, elem):
        if self.items is None:
            raise ValueError("must be used within a context.")

        # Make the string now, since it may stall and we don't wanna do that mid-
        # print.
        self.tostr(elem)

        # If not sorted, just add and print the element.
        if self.key is None:
            self.items.append(elem)
            sys.stdout.write(self.tostr(elem) + "\n")
            return

        # Add the element, maintaining the sort.
        idx = self._bsearch(elem)
        self.items.insert(idx, elem)

        # Reprint the elements.
        space = cons.move_up(len(self.items) - 1)
        # If there's still space on the screen, add another element.
        if cons.pos()[0] > 1:
            space += 1
        if space > 0: # since -0 = 0
            for item in self.items[-space:]:
                cons.clear_line()
                sys.stdout.write(self.tostr(item) + "\n")
            sys.stdout.flush()



def main():
    parser = argparse.ArgumentParser(prog="ls",
            description="List current directory contents.")

    group_size = parser.add_mutually_exclusive_group()
    group_size.add_argument("-s", "--size", action="store_true",
            help="include the sizes of entries")
    group_size.add_argument("-S", "--long-size", action="store_true",
            help="include the sizes of entries, in long format")

    parser.add_argument("-x", "--sort",
            choices=["x", "s", "size", "n", "name"],
            help="sort the output by some attribute")


    args = parser.parse_args()

    components = [lambda e: e.path]
    if args.size:
        components.insert(0, lambda e: e.size(long=False))
    if args.long_size:
        components.insert(0, lambda e: e.size(long=True))

    key = Entry.sort_name
    if args.sort:
        if args.sort[0] == "x":
            key = None
        if args.sort[0] == "s":
            key = Entry.sort_size
        if args.sort[0] == "n":
            key = Entry.sort_name
    tostr = lambda e: "  ".join(c(e) for c in components)

    with PRS(key, tostr) as prs:
        try:
            it = os.scandir(".")
        except OSError as e:
            print(f"ls: error: {e}")
        else:
            with it:
                for p in it:
                    prs.insert(Entry.create(p))


if __name__ == "__main__":
    main()
