import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path



class cons:
    """ Simple console printing handler. """

    @classmethod
    def write(cls, obj):
        """ Output the given object. """
        sys.stdout.write(str(obj))

    @classmethod
    def flush(cls):
        """ Flush any output. """
        sys.stdout.flush()

    @classmethod
    def length(cls, string):
        """ Returns the number of characters the given string has when output
        (aka the length of the string without control codes). """
        # Remove the control codes.
        control_code = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        string = control_code.sub("", string)
        return len(string)


    # Control codes from:
    # https://gist.github.com/fnky/458719343aabd01cfb17a3a4f7296797

    # hack to enable the control sequences.
    os.system("")

    class Colour:
        ENABLED = True
        def __init__(self, cid):
            self.cid = cid

        def __call__(self, string):
            if self.ENABLED:
                return f"\x1B[38;5;{self.cid}m{string}\x1B[0m"
            return string

        def __enter__(self):
            if self.ENABLED:
                cons.write(f"\x1B[38;5;{self.cid}m")
        def __exit__(self, etype, evalue, traceback):
            if self.ENABLED:
                cons.write("\x1B[0m")
            return False

    @classmethod
    def pos(cls):
        """ Returns the current cursor position, as 1-based row,column. """
        # https://stackoverflow.com/a/69582478

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
            cls.write("\x1B[6n")
            cls.flush()
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

    @classmethod
    def clear_line(cls):
        """ Clears the line under the cursor. """
        cls.write("\x1B[2K\r")

    @classmethod
    def move_up(cls, by):
        """ Attempts to move the cursor up by `by` lines. Returns the number of
        lines it actually moved up. """
        if by <= 0:
            return 0
        y, _ = cls.pos()
        do = min(y - 1, by)
        cls.write(f"\x1B[{do}A")
        return do



class Entry:
    """ Stores a single entry in the directory. """

    def __init__(self, dir_entry):
        self._name = dir_entry.name
        self._path = dir_entry.path
        self._isdir = dir_entry.is_dir()
        self._ctime = dir_entry.stat().st_birthtime
        self._mtime = dir_entry.stat().st_mtime
        self._size = None
        self._subfiles = None
        self._subdirs = None

        # Process files now.
        if not self._isdir:
            self._size = dir_entry.stat().st_size
            # Use -2 to sort files before failed directories.
            self._subfiles = -2
            self._subdirs = -2
        # But leave dir processing (since its expensive) for when they queried.

    def name(self):
        """ Returns the name of this entry. """
        return self._name

    def path(self):
        """ Returns the path of this entry, for displaying. """
        path = self._name + "/"*(self._isdir)
        quote = False

        # Replace controls codes with codepoints.
        for i in range(32):
            quote = quote or (chr(i) in path)
            path = path.replace(chr(i), repr(chr(i)))

        # Quote also if end or start with weird characters.
        end_or_start = lambda c: path.startswith(c) or path.endswith(c)
        if end_or_start(" ") or end_or_start("\"") or end_or_start("'"):
            quote = True

        if quote:
            quote = "'"
            if "'" in path:
                quote = "\""
            path = path.replace("\\", "\\\\")
            path = path.replace(quote, "\\" + quote)
            path = quote + path + quote

        return path

    def isdir(self):
        """ Returns true if this entry is a directory. """
        return self._isdir

    def ctime(self):
        """ Returns the creation time of this entry, as a datetime object. """
        return datetime.fromtimestamp(self._ctime)

    def mtime(self):
        """ Returns the last modification time of this entry, as a datetime
        object. """
        return datetime.fromtimestamp(self._mtime)

    def size(self):
        """ Returns the size of this entry, in bytes. May return -1, indicating
        failure to get the size. """
        if self._size is None:
            self._dir_process()
        return self._size

    def subfiles(self):
        """ Returns the number of files within the tree of this entry, only
        applicable for directories. May return -1, indicating failure to get the
        number of files. """
        if self._subfiles is None:
            self._dir_process()
        return self._subfiles

    def subdirs(self):
        """ Returns the number of directories within the tree of this entry, only
        applicable for directories. May return -1, indicating failure to get the
        number of directories. """
        if self._subdirs is None:
            self._dir_process()
        return self._subdirs


    def _dir_process(self):
        assert self._isdir
        # Process contents, in a simple dfs.
        self._size = 0
        self._subfiles = 0
        self._subdirs = 0
        stack = [self._path]
        while stack:
            try:
                it = os.scandir(stack.pop())
            except OSError:
                # If any subdirectory fails, we dont report anything for the
                # directory.
                self._size = -1
                self._subfiles = -1
                self._subdirs = -1
                break
            with it:
                for p in it:
                    if p.is_file():
                        self._subfiles += 1
                        self._size += p.stat().st_size
                    else:
                        self._subdirs += 1
                        stack.append(p.path)



class Key:
    """ Key functions for sorting. """

    @classmethod
    def reverse(cls, key):
        """ When given a sort key, returns a new sort key which can be used to
        sort in the reverse order as `key` would. """
        # Cheeky wrapper to invert the comparison of the object resulting from
        # `key(...)`.
        class Reversed:
            def __init__(self, *args, **kwargs):
                self.obj = key(*args, **kwargs)
            def __lt__(self, other):
                return not (self.obj < other.obj)
        return Reversed

    @classmethod
    def name(cls, entry):
        """ Use as a sort key to sort by entry name. """
        return not entry.isdir(), entry.name().casefold(), entry.name()

    @classmethod
    def ctime(cls, entry):
        """ Use as a sort key to sort by entry creation time. """
        return entry.ctime(), *cls.name(entry)

    @classmethod
    def mtime(cls, entry):
        """ Use as a sort key to sort by entry modification time. """
        return entry.mtime(), *cls.name(entry)

    @classmethod
    def size(cls, entry):
        """ Use as a sort key to sort by entry size. """
        return entry.size(), *cls.name(entry)

    @classmethod
    def subfiles(cls, entry):
        """ Use as a sort key to sort by entry subfile count. """
        return entry.subfiles(), *cls.name(entry)

    @classmethod
    def subdirs(cls, entry):
        """ Use as a sort key to sort by entry subdirectory count. """
        return entry.subdirs(), *cls.name(entry)



class Format:
    """ Conversion functions for objects to strings. """

    # 1024-based prefixes.
    PREFIXES = ["", "k", "M", "G", "T", "P", "E", "Z", "Y", "R", "Q"]

    @classmethod
    def number(cls, num, long=False, unit=""):
        """ Returns a fixed-width string of the given number. """
        # short: "xxxP"
        # long:  "xxxxx PU"
        if num < 0:
            if long:
                u = "?" if (unit) else ""
                return f" ???? {u} "
            else:
                return " ???"

        # If short, we dont wanna write 4 digits. In long tho, just use the most
        # accurate prefix.
        limit = 1024 if (long) else 1000

        # Find the correct magnitude.
        try:
            num = float(num)
        except OverflowError:
            num = float("inf")
        prefix = 0
        while num >= limit and prefix < len(cls.PREFIXES) - 1:
            num /= 1024
            prefix += 1

        # More than quettabytes?
        if num >= limit:
            if long:
                return f" lots {unit} "
            else:
                return "lots"

        # Make the final number+prefix+unit.
        if long:
            suffix = f" {cls.PREFIXES[prefix] + unit:<{1 + len(unit)}}"
        else:
            suffix = f"{cls.PREFIXES[prefix]:<1}"
        digits = 5 if (long) else 3

        # Special case for short when prefix is "", since we can use the space
        # for something. If a single-char uit is given, use it for that.
        # Otherwise, use it for an extra digit.
        if not long and prefix == 0:
            if not unit:
                digits += 1
                suffix = ""
            elif len(unit) == 1:
                suffix = unit

        s = f"{num:.{digits}f}"
        s = s[:digits]
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return f"{s:>{digits}}{suffix}"

    @classmethod
    def time(cls, time, long=False):
        """ Returns a fixed-width string of the given datetime object. """
        if long:
            return time.strftime("%Y-%m-%d %H:%M:%S.%f")
        else:
            return time.strftime("%Y-%m-%d")



class PRS:
    """ Print running sort. Items are printed in a sorted list, reprinting with
    every insertion. Use in a context, and is scrubbed fresh with each one. """

    def __init__(self, key, tostr):
        self.key = key
        self.tostr = tostr
        self.items = None

    def __enter__(self):
        self.items = []
        return self

    def __exit__(self, etype, evalue, traceback):
        if etype is None:
            # If succeeded then we gotta wipe the printed output and reprint the
            # full outupt.
            cons.move_up(len(self.items))
            for item in self.items:
                cons.clear_line()
                cons.write(self.tostr(item) + "\n")
            cons.flush()
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
        """ Inserts the given element, reprinting the sorted list that has been
        constructed so far. """
        assert self.items is not None

        # Make the string now, since it may stall and we don't wanna do that mid-
        # print.
        self.tostr(elem)

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
                cons.write(self.tostr(item) + "\n")
            cons.flush()



class PCL:
    """ Print columned list. No running logic needed, just adopts a similar api
    to PRS to allow for code to use either. """

    def __init__(self, key, tostr, max_width=100, min_column_width=16, pad=1,
            max_columns=4):
        self.key = key
        self.tostr = tostr
        self.max_width = max_width
        self.min_column_width = min_column_width
        self.pad = pad
        self.max_columns = max_columns
        self.items = None

    def __enter__(self):
        self.items = []
        return self

    def __exit__(self, etype, evalue, traceback):
        # Just exit on exception.
        if etype is not None:
            return False
        # Nothing to print.
        if not self.items:
            return False

        # Do the entire print.
        self.items = sorted(self.items, key=self.key)
        strings = [self.tostr(item) for item in self.items]
        max_length = max(cons.length(s) for s in strings)

        # Get the number of rows/columns to print.
        columns = self.max_width // max_length
        columns = max(1, min(self.max_columns, columns)) # clamp.
        rows = (len(strings) + columns - 1) // columns

        # If we have more than 1 column, gotta calculate how much padding we need
        # for the non-last columns.
        if columns > 1:
            # Calc the smallest width, without shrinking past min width.
            without_last_column = strings[:(columns - 1) * rows]
            wlc_max_length = max(cons.length(s) for s in without_last_column)
            width = max(self.min_column_width, wlc_max_length + 4)

        # Catch edge cases where some columns are empty.
        filled_columns = (len(strings) + rows - 1) // rows
        missing_cols = columns - filled_columns
        if missing_cols > 0:
            # Fill the last column except one.
            missing = rows*columns - 1 - len(strings)
            for i in range(missing):
                col = columns - 1 - missing + i
                at = rows*col + rows - 1
                strings.insert(at, "")

        # Print each row.
        for i in range(rows):
            row = strings[i::rows]
            line = [" "*self.pad]
            for item in row[:-1]:
                line.append(item + " "*(width - cons.length(item)))
            line.append(row[-1])
            cons.write("".join(line) + "\n")
        cons.flush()

        return False

    def insert(self, elem):
        """ Inserts the given element, adding it to be printed on exit. """
        if self.items is None:
            raise ValueError("must be used within a context.")

        # Add the element, not bothering with sort.
        self.items.append(elem)



def main():
    parser = argparse.ArgumentParser(prog="ls",
            description="List directory contents. Note the displayed attributes "
                "are always in the order of: ctime, mtime, subfile count, "
                "subdir count, size, path (where each attribute is only present "
                "if requested).")

    parser.add_argument("path", metavar="PATH", nargs="?", default=".",
            help="which directory's contents to list (defaults to here)")

    group_fd = parser.add_mutually_exclusive_group()
    group_fd.add_argument("-f", "--files", action="store_true",
            help="only list files")
    group_fd.add_argument("-d", "--directories", action="store_true",
            help="only list directories")

    group_ctime = parser.add_mutually_exclusive_group()
    group_ctime.add_argument("-c", "--ctime", action="store_true",
            help="include creation time")
    group_ctime.add_argument("-C", "--long-ctime", action="store_true",
            help="'-c' in long format")

    group_mtime = parser.add_mutually_exclusive_group()
    group_mtime.add_argument("-m", "--mtime", action="store_true",
            help="include last modification time")
    group_mtime.add_argument("-M", "--long-mtime", action="store_true",
            help="'-m' in long format")

    group_size = parser.add_mutually_exclusive_group()
    group_size.add_argument("-s", "--size", action="store_true",
            help="include size")
    group_size.add_argument("-S", "--long-size", action="store_true",
            help="'-s' in long format")

    group_count = parser.add_mutually_exclusive_group()
    group_count.add_argument("-n", "--sub-counts", action="store_true",
            help="include number of sub-files/directories")
    group_count.add_argument("-N", "--long-sub-counts", action="store_true",
            help="'-n' in long format")

    group_sort = parser.add_mutually_exclusive_group()
    group_sort.add_argument("-x", "--sort",
            choices=["c", "m", "s", "nf", "nd"],
            nargs="?", default=0, const=1,
            help="sort in ascending order by some attribute; key may be "
                "inferred if not explicit")
    group_sort.add_argument("-X", "--reverse-sort",
            choices=["c", "m", "s", "nf", "nd"],
            nargs="?", default=0, const=1,
            help="'-x' in descending order")

    parser.add_argument("--no-col", "--no-colour", "--no-color",
            action="store_true",
            help="disable colour in output")

    args = parser.parse_args()


    # Disable colour :(
    if args.no_col:
        cons.Colour.ENABLED = False


    # Get the filter for what to display.
    cull = lambda e: False
    if args.files:
        cull = lambda e: e.isdir()
    if args.directories:
        cull = lambda e: not e.isdir()


    # Create each of the string/output components.
    palette = [63, 98, 126, 43, 80, 120]
    # roughly: blue, purple, magenta, cyan, file=light blue, dir=light green.
    components = []
    if args.ctime or args.long_ctime:
        col = cons.Colour(palette[0])
        f = lambda e, c=col: c(Format.time(e.ctime(), args.long_ctime))
        components.append(f)
    if args.mtime or args.long_mtime:
        col = cons.Colour(palette[1])
        f = lambda e, c=col: c(Format.time(e.mtime(), args.long_mtime))
        components.append(f)
    if args.sub_counts or args.long_sub_counts:
        col = cons.Colour(palette[2])
        def comp(e, n, c=col):
            count = c(Format.number(n, args.long_sub_counts))
            if e.isdir():
                return count
            return " "*cons.length(count)
        components.append(lambda e: comp(e, e.subfiles()))
        components.append(lambda e: comp(e, e.subdirs()))
    if args.size or args.long_size:
        col = cons.Colour(palette[3])
        f = lambda e, c=col: c(Format.number(e.size(), args.long_size, "B"))
        components.append(f)

    f = lambda e: cons.Colour(palette[4 + e.isdir()])(e.path())
    components.append(f)

    # Join the thangs to make the complete string. Note the ordering of each
    # attribute is fixed (ctime -> mtime -> size -> counts -> path).
    pad = " " * (len(components) > 1)
    tostr = lambda e: pad + "  ".join(c(e) for c in components)


    # Get the key to sort by (defaulting to name).
    key = Key.name
    sortby = None
    # Check inferred sorting.
    if args.sort == 1 or args.reverse_sort == 1:
        sortby = ""
        if args.ctime or args.long_ctime:
            sortby += "c"
        if args.mtime or args.long_mtime:
            sortby += "m"
        if args.size or args.long_size:
            sortby += "s"
        if args.sub_counts or args.long_sub_counts:
            sortby += "too many"
        if len(sortby) != 1:
            arg = "-x/--sort" if (args.sort) else "-X/--reverse-sort"
            if len(sortby) > 1:
                reason = "too many included attributes"
            else:
                reason = "no included attributes"
            parser.error(f"argument {arg}: cannot infer sort key: {reason}")
    # Otherwise just grab the explicit.
    elif args.sort:
        sortby = args.sort
    elif args.reverse_sort:
        sortby = args.reverse_sort

    # Update sorting key.
    if sortby:
        if sortby == "c":
            key = Key.ctime
        if sortby == "m":
            key = Key.mtime
        if sortby == "s":
            key = Key.size
        if sortby == "nf":
            key = Key.subfiles
        if sortby == "nd":
            key = Key.subdirs

    # Reverse if requested.
    if args.reverse_sort:
        key = Key.reverse(key)


    # Special column printing if no extra attributes or sorting are requested.
    if len(components) == 1 and not sortby:
        obj = PCL(key, tostr)
    # If any extra attributes or sorting have been requested, do the print-
    # running-sort single-column vertical list.
    else:
        obj = PRS(key, tostr)

    # Using this wack api we'eve constructed, process all the items in this
    # directory.
    with obj:
        try:
            it = os.scandir(args.path)
        except OSError as e:
            cons.write(f"ls: error: {e}")
            cons.flush()
            return
        with it:
            for p in it:
                e = Entry(p)
                if cull(e):
                    continue
                obj.insert(e)


if __name__ == "__main__":
    main()
