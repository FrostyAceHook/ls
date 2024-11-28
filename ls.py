import argparse
import os
import re
import shutil
import sys
from datetime import datetime, timedelta
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

    @classmethod
    def clear_line(cls):
        """ Clears the line under the cursor. """
        cls.write("\x1B[2K\r")

    @classmethod
    def move_up(cls, by):
        """ Moves the cursor up by `by` lines. Note that if this may stop short
        if the cursor hits the top of the console. """
        if by <= 0:
            return 0
        cls.write(f"\x1B[{by}A")

    class Colour:
        """ Colouring text. May be used as a context (non-nested) to colour all
        text printed while in it. """

        ENABLED = True
        def __init__(self, cid):
            self.cid = cid

        def __call__(self, string):
            """ Returns the given string with control codes inserted to colour
            it. """
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
        return self._name + "/"*(self._isdir)

    def isdir(self):
        """ Returns true if this entry is a directory. """
        return self._isdir

    def ext(self):
        """ Return the extension of this entry. """
        if self._isdir or "." not in self._name:
            return ""
        return self._name[self._name.rfind("."):]

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
    def ext(cls, entry):
        """ Use as a sort key to sort by entry extension. """
        return entry.ext().casefold(), entry.ext(), *cls.name(entry)

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

    @classmethod
    def _fixedlength(cls, num, length):
        # return the most-accurate rep of `num` as a `length` character string.

        # Do rounding.
        s = f"{num:.{length}f}"
        i = s.index(".")
        if i > length: # cannot fit within `length` characters.
            return None
        d = length - 1 - i if (i < length) else 0
        num = round(num, d)
        # Do culling.
        s = f"{num:.{length}f}"
        s = s[:length]
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        # Do padding.
        return f"{s:>{length}}"


    @classmethod
    def path(cls, path):
        CONTROL_CODES = [chr(i) for i in range(0x00, 0x20)]
        CONTROL_CODES += [chr(i) for i in range(0x7F, 0xA0)]
        quote = False

        # Quote if end or start with weird characters.
        end_or_start = lambda c: path.startswith(c) or path.endswith(c)
        if end_or_start(" ") or end_or_start("\"") or end_or_start("'"):
            quote = True

        # Quote if any control codes are present.
        if any(i in path for i in CONTROL_CODES):
            quote = True

        # Do standard quoting stuff.
        if quote:
            quote = "'"
            if "'" in path:
                quote = "\""
            path = path.replace("\\", "\\\\")
            path = path.replace(quote, "\\" + quote)
            path = quote + path + quote

        # After escaping everything, replace the control codes with escape
        # sequences.
        for i in CONTROL_CODES:
            path = path.replace(i, repr(i)[1:-1])

        return path


    @classmethod
    def number(cls, num, long=False, unit=""):
        """ Returns a fixed-width string of the given number. """
        # short: "xxxP"
        # long:  "xxxxx PU"

        # 1024-based prefixes.
        PREFIXES = ["", "k", "M", "G", "T", "P", "E", "Z", "Y", "R", "Q"]

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
        while num >= limit and prefix < len(PREFIXES) - 1:
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
            suffix = f" {PREFIXES[prefix] + unit:<{1 + len(unit)}}"
        else:
            suffix = f"{PREFIXES[prefix]:<1}"
        digits = 5 if (long) else 3

        # Special case for short when prefix is "", since we can use the space
        # for something. If a single-char unit is given, use it for that.
        # Otherwise, use it for an extra digit.
        if not long and PREFIXES[prefix] == "":
            if not unit:
                digits += 1
                suffix = ""
            elif len(unit) == 1:
                suffix = unit
        # Convert and make final result.
        s = cls._fixedlength(num, digits)
        assert s is not None
        return f"{s}{suffix}"


    # Cache current time, so that all timestamps are relative to the same thing.
    NOW = datetime.now()

    @classmethod
    def time(cls, time, long=False, now=None):
        """ Returns a fixed-width string of the given datetime object. """
        # short: "xxxU ago" (how long ago)
        #    or; " yyyy-mm" (timestamp)
        # long:  "yyyy-mm-dd HH:MM:SS.UUUUUUU" (timestamp)

        if now is None:
            now = cls.NOW

        # If long, just return the exact timestamp.
        if long:
            return time.strftime("%Y-%m-%d %H:%M:%S.%f")

        # Otherwise find a rep for how long ago.
        ago = now - time
        UNITS = [
            ("s ago", timedelta(seconds=1), 120),
            ("m ago", timedelta(minutes=1), 120),
            ("h ago", timedelta(hours=1),   48),
            ("d ago", timedelta(hours=24),  100),
        ]
        digits = 3
        ulength = len(UNITS[0][0])

        for unit, scale, cutoff in UNITS:
            num = ago / scale
            # check not beyond cutoff (note this is only done for
            # understandidababilility)
            if num >= cutoff:
                continue
            s = cls._fixedlength(num, digits)
            if s is None: # check not too long.
                continue
            return f"{s}{unit}"

        # Otherwise too long ago, so just return the month (padded).
        return f"{time.strftime("%Y-%m"):>{digits + ulength}}"



class PRS:
    """ Print running sort. Items are printed in a sorted multi-column list,
    reprinting with every insertion. Use it in a context, where each context gets
    fresh contents. """

    def __init__(self, key, tostr, max_total_width=100, min_width=16, padding=5,
            max_columns=4, no_running=False, row_wise=False,
            uniform_width=False, spacing=timedelta(seconds=0.1)):
        self.key = key
        self.tostr = tostr
        self.max_total_width = max_total_width
        self.min_width = min_width
        self.padding = padding
        self.max_columns = max_columns
        self.no_running = no_running
        self.row_wise = row_wise
        self.uniform_width = uniform_width
        self.spacing = spacing
        self.items = None # list of (item, tostr(item))
        self.prev_lines = None # number of lines printed before.
        self.prev_time = None # time of previous print.

    def _bsearch(self, elem):
        # Binary search.
        left, right = 0, len(self.items)
        while left < right:
            mid = (left + right) // 2
            if self.key(self.items[mid][0]) < self.key(elem):
                left = mid + 1
            else:
                right = mid
        return left

    def _max_width_of(self, strings):
        max_width = max(cons.length(s) for s in strings)
        max_width += self.padding
        max_width = max(self.min_width, max_width)
        return max_width

    def _contents(self, strings, columns):
        # Single column always works.
        if columns == 1:
            return ([s] for s in strings), [self._max_width_of(strings)]

        # Make a copy to ensure we don't modify the actual object.
        strings = strings[:]

        # Calculate the number of rows required.
        rows = (len(strings) + columns - 1) // columns

        # Catch a column-wise edge case where some columns would be empty.
        if not self.row_wise:
            filled_columns = (len(strings) + rows - 1) // rows
            missing_cols = columns - filled_columns
            if missing_cols > 0:
                # Fill the last column except one.
                missing = rows*columns - 1 - len(strings)
                for i in range(missing):
                    col = columns - 1 - missing + i
                    at = rows*col + rows - 1
                    strings.insert(at, "")

        # Pad to a square grid.
        strings += [""] * (rows*columns - len(strings))

        # Make a column-getter.
        if self.row_wise:
            columnat = lambda c: [s for i, s in enumerate(strings)
                                  if i % columns == c]
        else:
            columnat = lambda c: [s for i, s in enumerate(strings)
                                  if c*rows <= i and i < (c + 1)*rows]

        # Calculate how much padding we need for each column.
        widths = [self._max_width_of(columnat(c)) for c in range(columns)]

        # Make width uniform if requested.
        if self.uniform_width:
            uniform = max(widths[:-1])
            for i in range(columns - 1):
                widths[i] = uniform

        # Calculate if this arrangement is possible.
        if sum(widths) > self.max_total_width:
            return None, None

        # Make a row-getter.
        if self.row_wise:
            rowat = lambda r: [s for i, s in enumerate(strings)
                               if r*columns <= i and i < (r + 1)*columns]
        else:
            rowat = lambda r: [s for i, s in enumerate(strings)
                               if i % rows == r]

        # Return the row contents and the column widths.
        return (rowat(r) for r in range(rows)), widths

    def _lines(self):
        if not self.items:
            return []
        strings = [string for item, string in self.items]

        # Try the column possibilities, in reverse order.
        for columns in range(self.max_columns, 0, -1):
            contents, widths = self._contents(strings, columns)
            if contents is not None: # take the first that works.
                break

        # Make each line as a string.
        lines = []
        for content in contents:
            line = []
            # Add slight beginning padding if there's multiple columns.
            if len(content) > 1:
                line.append(" ")
            # Pad the non-last-column elements.
            for column, item in enumerate(content[:-1]):
                padding = widths[column] - cons.length(item)
                line.append(item + " "*padding)
            line.append(content[-1])
            lines.append("".join(line))
        return lines

    def __enter__(self):
        self.items = []
        self.prev_lines = 0
        self.prev_time = None
        return self

    def __exit__(self, etype, evalue, traceback):
        # If succeeded then we gotta wipe the printed output and reprint the full
        # outupt.
        if etype is None:
            lines = self._lines()
            cons.move_up(self.prev_lines)
            for line in lines:
                cons.clear_line()
                cons.write(line + "\n")
            cons.flush()
        # Reset the container.
        self.items = None
        self.prev_lines = 0
        self.prev_time = None
        return False


    def insert(self, elem):
        """ Inserts the given element, reprinting the sorted list that has been
        constructed so far. """
        assert self.items is not None

        # Add the element, maintaining the sort.
        idx = self._bsearch(elem)
        self.items.insert(idx, (elem, self.tostr(elem)))

        # Don't print running if not requested.
        if self.no_running:
            return

        # Don't print if the most-recent print was not long ago.
        now = datetime.now()
        if self.prev_time is not None:
            if now - self.prev_time < self.spacing:
                return
        self.prev_time = now

        # Reprint the elements.
        lines = self._lines()

        # Overwrite the previous print.
        cons.move_up(self.prev_lines)
        # Try to use all the lines on the screen, leaving space for the
        # terminating \n.
        space = shutil.get_terminal_size().lines - 1
        self.prev_lines = 0
        if space > 0: # since -0 = 0
            for line in lines[-space:]:
                cons.clear_line()
                cons.write(line + "\n")
                self.prev_lines += 1
            cons.flush()



def main():
    parser = argparse.ArgumentParser(prog="ls",
            description="List directory contents. Note the displayed attributes "
                "are always in the order of: creation time, last modification "
                "time, number of sub-files, number of sub-directories, size, "
                "path (where each attribute is only present if requested).")

    parser.add_argument("path", metavar="PATH", nargs="?", default=".",
            help="which directory's contents to list (defaults to here)")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("-f", "--files", action="store_true",
            help="only list files")
    group.add_argument("-d", "--directories", action="store_true",
            help="only list directories")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--ctime", action="store_true",
            help="include creation time")
    group.add_argument("-C", "--long-ctime", action="store_true",
            help="'-c' in long format")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("-m", "--mtime", action="store_true",
            help="include last modification time")
    group.add_argument("-M", "--long-mtime", action="store_true",
            help="'-m' in long format")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("-n", "--sub-counts", action="store_true",
            help="include number of sub-files/sub-directories for directories")
    group.add_argument("-N", "--long-sub-counts", action="store_true",
            help="'-n' in long format")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("-s", "--size", action="store_true",
            help="include size")
    group.add_argument("-S", "--long-size", action="store_true",
            help="'-s' in long format")

    parser.add_argument("-e", "--extensions", action="store_true",
            help="highlight extensions")

    INFERRED = object()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-x", "--sort",
            choices=["n", "c", "m", "nf", "nd", "s", "e"],
            nargs="?", default=None, const=INFERRED,
            help="sort in ascending order by some key, which may be inferred if "
                "not explicit"
                "; n - name"
                "; c - creation time"
                "; m - last modification time"
                "; nf - number of sub-files"
                "; nd - number of sub-directories"
                "; s - size"
                "; e - extensions"
            )
    group.add_argument("-X", "--reverse-sort",
            choices=["n", "c", "m", "nf", "nd", "s", "e"],
            nargs="?", default=None, const=INFERRED,
            help="'-x' in descending order")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("-1", "--single-column", action="store_true",
            help="display as a single column")
    group.add_argument("--columns", metavar="COUNT", type=int,
            help="display with at-most this many columns")

    parser.add_argument("--no-colour", action="store_true",
            help="display without colour")

    parser.add_argument("--no-running", action="store_true",
            help="display only once finished")

    parser.add_argument("--row-wise", action="store_true",
            help="display sorted row-wise instead of column-wise")

    parser.add_argument("--uniform-width", action="store_true",
            help="display with equal-width columns")

    args = parser.parse_args()


    # Get the filter for what to display.
    cull = lambda e: False
    if args.files:
        cull = lambda e: e.isdir()
    if args.directories:
        cull = lambda e: not e.isdir()


    # Create each of the string/output components.
    P = { # colour palette.
        "ctime": cons.Colour(63), # blue
        "mtime": cons.Colour(98), # purple
        "sub_counts": cons.Colour(126), # magenta
        "size": cons.Colour(43), # cyan
        "ext": cons.Colour(220), # gold
        "file": cons.Colour(80), # light blue
        "dir": cons.Colour(120), # light green
    }
    components = []
    if args.ctime or args.long_ctime:
        f = lambda e: P["ctime"](Format.time(e.ctime(), args.long_ctime))
        components.append(f)
    if args.mtime or args.long_mtime:
        f = lambda e: P["mtime"](Format.time(e.mtime(), args.long_mtime))
        components.append(f)
    if args.sub_counts or args.long_sub_counts:
        def comp(e, n):
            count = P["sub_counts"](Format.number(n, args.long_sub_counts))
            if e.isdir():
                return count
            return " "*cons.length(count)
        components.append(lambda e: comp(e, e.subfiles()))
        components.append(lambda e: comp(e, e.subdirs()))
    if args.size or args.long_size:
        f = lambda e: P["size"](Format.number(e.size(), args.long_size, "B"))
        components.append(f)

    def pathstring(e):
        path = Format.path(e.path())
        if e.isdir():
            return P["dir"](path)
        if not args.extensions or "." not in path:
            return P["file"](path)
        # otherwise gotta highlight extension.
        if path[0] == "'" or path[0] == "\"": # if quoted
            # Exclude the quote in the highlight.
            a = path[:path.rfind(".")]
            b = path[path.rfind("."):-1]
            c = path[-1]
            return P["file"](a) + P["ext"](b) + P["file"](c)
        a = path[:path.rfind(".")]
        b = path[path.rfind("."):]
        return P["file"](a) + P["ext"](b)
    components.append(pathstring)

    # Join the thangs to make the complete string. Note the ordering of each
    # attribute is fixed.
    pad = " " * (len(components) > 1)
    tostr = lambda e: pad + "  ".join(c(e) for c in components)


    # Get the key to sort by.
    sortby = ""
    # Check inferred sorting.
    if args.sort is INFERRED or args.reverse_sort is INFERRED:
        if args.ctime or args.long_ctime:
            sortby += "c"
        if args.mtime or args.long_mtime:
            sortby += "m"
        if args.sub_counts or args.long_sub_counts:
            sortby += "too many"
        if args.size or args.long_size:
            sortby += "s"
        if args.extensions:
            sortby += "e"
        if len(sortby) > 1:
            arg = "-x/--sort" if (args.sort) else "-X/--reverse-sort"
            parser.error(f"argument {arg}: cannot infer sort key: too many "
                    "included attributes")
    # Otherwise just grab the explicit.
    elif args.sort:
        sortby = args.sort
    elif args.reverse_sort:
        sortby = args.reverse_sort

    # Get the sorting key (defaulting to name).
    key = Key.name
    if sortby == "n":
        key = Key.name
    if sortby == "c":
        key = Key.ctime
    if sortby == "m":
        key = Key.mtime
    if sortby == "nf":
        key = Key.subfiles
    if sortby == "nd":
        key = Key.subdirs
    if sortby == "s":
        key = Key.size
    if sortby == "e":
        key = Key.ext

    # Reverse if requested.
    if args.reverse_sort:
        key = Key.reverse(key)


    # Get the number of columns in the output (defaulting to 4 if no extra info,
    # otherwise single-column).
    columns = 1 if (len(components) > 1 or args.extensions) else 4
    if args.single_column:
        columns = 1
    if args.columns is not None:
        columns = args.columns


    # Disable colour :(
    if args.no_colour:
        cons.Colour.ENABLED = False


    # Make the printing object.
    prs = PRS(key, tostr, max_columns=columns, no_running=args.no_running,
            row_wise=args.row_wise, uniform_width=args.uniform_width)

    # Using this wack api we've constructed, process all the items in this
    # directory.
    try:
        it = os.scandir(args.path)
    except OSError as e:
        cons.write(f"ls: error: {e}\n")
        cons.flush()
        return
    with prs, it:
        for p in it:
            e = Entry(p)
            if cull(e):
                continue
            prs.insert(e)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cons.write("Interrupted.\n")
        cons.flush()
        sys.exit(130)
