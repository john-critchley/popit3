#!/usr/bin/python3
import json
import errno
import dbm.gnu as gdbm


class GDataLockedError(gdbm.error):
    """Database is locked for writing."""

    pass

class gdata_raw:
    """
    A base class for working with gdbm (GNU Database Manager) databases. 
    Provides basic dictionary-like access to a gdbm file.

    Args:
        gdbm_file (str): The filename of the gdbm database. Defaults to '.gdbm'.
        mode (str): The file mode used for opening the gdbm file. Defaults to 'c' 
                    (create if not existing).
        mask (int): File permissions mask for the gdbm file. Defaults to 0o600.
    
    Attributes:
        db: The gdbm database object.
        open (bool): A flag indicating whether the database is open.
    """
    
    def __init__(self, gdbm_file='.gdbm', mode='c', mask=0o600):
        try:
            self.db = gdbm.open(gdbm_file, mode, mask)
        except gdbm.error as e:
            # errno.EAGAIN is the typical indicator that the database
            # file is currently locked by another writer.
            if getattr(e, 'errno', None) == errno.EAGAIN:
                raise GDataLockedError(str(e)) from e
            raise
        self.open = True

    def __enter__(self):
        """Supports using the class as a context manager (with statement)."""
        return self

    def __exit__(self, *blah):
        """Closes the gdbm file when exiting a context manager block."""
        self.close()
        return False

    def close(self):
        """Closes the gdbm file."""
        self.db.close()
        self.open = False

    def __del__(self):
        """Ensures that the gdbm file is closed when the object is destroyed."""
        if 'open' in dir(self) and self.open:
            self.db.close()

    def __getitem__(self, key):
        """Retrieve an item by key, raises KeyError if not found."""
        return self.db[key]

    def __contains__(self, key):
        """Check if a key exists in the database."""
        return key in self.db

    def __setitem__(self, key, item):
        """Set an item in the database."""
        self.db[key] = item

    def __delitem__(self, key):
        """Delete an item from the database."""
        del self.db[key]

    def __iter__(self):
        """Prepare the database for iteration over keys."""
        self.current_item = None
        return self

    def __next__(self):
        """
        Iterate over the keys in the database.
        Raises StopIteration when all keys are iterated over.
        """
        self.current_item = self.db.firstkey() if self.current_item is None else self.db.nextkey(self.current_item)
        if self.current_item is None:
            raise StopIteration
        return self.current_item

    def get(self, key, default=None):
        """
        Get the value for a key. If the key doesn't exist, return the default value.
        """
        return self.__getitem__(key) if self.__contains__(key) else default

    def keys(self):
        """
        Return a set of all keys in the database.
        """
        return set(self)

    def items(self):
        """
        Return a generator of key-value pairs in the database.
        """
        return ((p, self[p]) for p in self)

    def __len__(self):
        """
        Return the number of items in the database.
        """
        return len(self.keys())

class gdata_simple(gdata_raw):
    """
    A subclass of gdata_raw for handling string data (UTF-8 encoded). 
    Provides automatic encoding/decoding of strings.
    """
    
    def __setitem__(self, key, item):
        """Store a string item with UTF-8 encoding."""
        super().__setitem__(key.encode('utf-8'), item.encode('utf-8'))

    def __getitem__(self, key):
        """Retrieve a string item and decode it from UTF-8."""
        return super().__getitem__(key.encode('utf-8')).decode('utf-8')

    def __contains__(self, key):
        """Check if a UTF-8 encoded key exists."""
        return super().__contains__(key.encode('utf-8'))

    def __delitem__(self, key):
        """Delete a UTF-8 encoded key."""
        super().__delitem__(key.encode('utf-8'))

    def __next__(self):
        """Iterate over keys and decode them from UTF-8."""
        return super().__next__().decode('utf-8')

    def __str__(self):
        """Return a string representation of all keys in the database."""
        return ','.join(list(self.keys()))

class gdata(gdata_simple):
    """
    A subclass of gdata_simple that stores and retrieves data as JSON.
    This allows for storing structured data.
    """
    
    def __setitem__(self, key, item):
        """Store the item as a JSON-encoded string."""
        super().__setitem__(key, json.dumps(item))

    def __getitem__(self, key):
        """Retrieve the item as a decoded JSON object."""
        return json.loads(super().__getitem__(key))
