# -----------------------------------------------------------------------------

""" Module providing a wrapper around the multiprocessing module.

Copyright (c) 2022 Cisco and/or its affiliates.
This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at

        https://developer.cisco.com/docs/licenses

All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.

"""

import itertools
import multiprocessing
from typing import (
    Any,
    Callable,
    Iterable,
)

__all__ = (
    "map_helper",
    "starmap_helper",
)


# Testing flag to disable multiprocessing during debugging or MUT, as it
# doesn't play nicely with mocking calls.
_MULTIPROCESSING = True


def map_helper(
    func: Callable[[Any], Any], iterable: Iterable[Any]
) -> Iterable[Any]:
    """
    Wrapper around 'map' to use the multiprocessing version by default but
    be able to disable this and fall back to single-threaded 'map' in UT.

    Arguments match those of 'map'.
    """
    if _MULTIPROCESSING:
        with multiprocessing.Pool() as pool:
            return pool.map(func, iterable)
    else:
        return map(func, iterable)


def starmap_helper(
    func: Callable[..., Any], iterable: Iterable[Iterable[Any]]
) -> Iterable[Any]:
    """
    Wrapper around 'starmap' to use the multiprocessing version by default but
    be able to disable this and fall back to single-threaded 'starmap' in UT.

    Arguments match those of 'starmap'.
    """
    if _MULTIPROCESSING:
        with multiprocessing.Pool() as pool:
            return pool.starmap(func, iterable)
    else:
        return itertools.starmap(func, iterable)
