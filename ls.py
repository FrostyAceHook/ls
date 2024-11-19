import os
from pathlib import Path
from dataclasses import dataclass



def ndigits(x, n):
    return s


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

    _byte_size: int = -1
    _subfiles: int = -1
    _subdirs: int = -1

    def _dir_process(self):
        if not self.isdir:
            raise ValueError("cannot dir process a file")
        # Process dirs, in a simple dfs.
        self._byte_size = 0
        self._subfiles = 0
        self._subdirs = 0
        stack = [self.name]
        while stack:
            with os.scandir(stack.pop()) as it:
                for p in it:
                    if p.is_file():
                        self._subfiles += 1
                        self._byte_size += p.stat().st_size
                    else:
                        self._subdirs += 1
                        stack.append(p.path)

    @property
    def byte_size(self):
        if self._byte_size == -1:
            self._dir_process()
        return self._byte_size
    @property
    def subfiles(self):
        if self._subfiles == -1:
            self._dir_process()
        return self._subfiles
    @property
    def subdirs(self):
        if self._subdirs == -1:
            self._dir_process()
        return self._subdirs


    def size(self, long=False):
        UNITS = ["k", "M", "G", "T", "P"]
        size = self.byte_size
        digits = 5 if (long) else 3

        if long and size <= 1024:
            return f"{size:>{digits + 1}} B "

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



def main():
    entries = []
    with os.scandir(".") as it:
        for p in it:
            entries.append(Entry.create(p))

    entries = sorted(entries, key=Entry.sort_name)
    # entries = sorted(entries, key=Entry.sort_size)

    for entry in entries:
        print(entry.size() + "  " + entry.path)


if __name__ == "__main__":
    main()
