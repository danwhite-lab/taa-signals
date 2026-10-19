"""Small five-minute, deep-copy caches for this page only; no database writes."""
from collections import OrderedDict
from copy import deepcopy
from functools import wraps
from threading import RLock
from time import monotonic
import pickle


def cache_data(ttl=300, show_spinner=False):
    def decorate(function):
        values, lock = OrderedDict(), RLock()
        @wraps(function)
        def cached(*args, **kwargs):
            # Locally serialized trusted arguments only; pickle is never loaded.
            key = pickle.dumps((args, kwargs))
            with lock:
                item = values.get(key)
                if item and monotonic() - item[0] < ttl:
                    values.move_to_end(key)
                    return deepcopy(item[1])
                result = function(*args, **kwargs)
                values[key] = (monotonic(), deepcopy(result))
                while len(values) > 256:
                    values.popitem(last=False)
                return result
        def clear():
            with lock:
                values.clear()
        cached.clear = clear
        return cached
    return decorate
