#!/usr/bin/env python3
# -----------------------------------------------------------------------------

""" Finding the package with the highest version of those supplied.

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

# This script takes in tuples for packages of the form
# <epoch>,<version>,<release> and prints the most recent ('highest') one.
#
# If a pkg with no epoch value is supplied, any comparisons with this pkg will
# ignore the epoch value of both packages.
#
# Example use: "highest_pkg_version a,b,c ,x,z e,f," will compare pkgs
# 1) epoch a,    version b, release c
# 2) epoch None, version x, release z
# 3) epoch e,    version f, release None
# And print the 'highest' one. In this case, it prints: ",x,z"
import argparse
import sys

from typing import Sequence, Tuple

import rpm


_EVRType = Tuple[str, str, str]


def _compare(tuple_1: _EVRType, tuple_2: _EVRType) -> int:
    """
    Compare two (epoch, ver, rel) tuples returning the labelCompare result.

    If one of these tuples has no epoch value, it disregards both epoch values.
    Note that any release value is higher than a blank release value.

    Returns 1 if tuple_1 > tuple_2
            0 if tuple_1 == tuple_2
           -1 if tuple_1 < tuple_2

    """
    if not tuple_1[0] or not tuple_2[0]:
        new_1 = list(tuple_1)
        new_2 = list(tuple_2)
        new_1[0] = new_2[0] = ""
        # Expand manually to placate the type checker
        tuple_1 = (new_1[0], new_1[1], new_1[2])
        tuple_2 = (new_2[0], new_2[1], new_2[2])

    return rpm.labelCompare(tuple_1, tuple_2)


def _get_highest_version(pkg_tuples: Sequence[_EVRType]) -> _EVRType:
    """
    Return the highest tuple (epoch, version, release) of pkg_tuples.

    :param pkg_tuples:
        List of pkg version tuples (epoch, version, release) to be compared.

    :return:
        The tuple of the highest version.

    """
    assert len(pkg_tuples) > 0
    highest_tup = pkg_tuples[0]
    for tup in pkg_tuples[1:]:
        if _compare(tup, highest_tup) > 0:
            highest_tup = tup

    return highest_tup


def _as_tuple(pkg_str: str) -> _EVRType:
    """
    Takes in a str "<epoch>,<version>,<release>" and returns this as a tuple.
    """
    e, v, r = pkg_str.split(",")
    return (e, v, r)


def main(argv: Sequence[str]) -> None:
    """The main function for the script."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "packages",
        nargs="+",
        help=(
            "Packages to be compared. Each package should be "
            "<epoch>,<version>,<release> (separated  with spaces). Pass in an "
            "empty string for an epoch value of None."
        ),
    )
    args = parser.parse_args(argv)

    # Extract tuples from the args passed in
    pkgs_to_compare = [_as_tuple(pkg) for pkg in args.packages]
    highest_tuple = _get_highest_version(pkgs_to_compare)

    print(
        "{},{},{}".format(highest_tuple[0], highest_tuple[1], highest_tuple[2])
    )


if __name__ == "__main__":
    main(sys.argv[1:])
