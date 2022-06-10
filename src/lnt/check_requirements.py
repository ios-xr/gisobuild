#!/usr/bin/env python3
# -----------------------------------------------------------------------------

"""Check if user has required dependencies, returning any that are missing

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

import importlib
import re
import shutil
import subprocess
import sys

from typing import List

# This tool has the following requirements:
#   rpm >= 4.14, with python bindings enabled
#   cpio >= 2.10
#   gzip >= 1.9
#   python >= 3.6
#   createrepo_c
#   isoinfo
#   mkisofs
#   mksquashfs
#   openssl
#   unsquashfs
# Python modules:
#   dataclasses
#   defusedxml
#   distutils
#   packaging
#   rpm
#   yaml
_REQUIRED_MODULES = [
    "dataclasses",
    "defusedxml",
    "distutils",
    "packaging",
    "rpm",
    "yaml",
]

_REQUIRED_EXCS = [
    "createrepo_c",
    "isoinfo",
    "mksquashfs",
    "unsquashfs",
    "mkisofs",
    "cpio",
    "gzip",
    "openssl",
    "rpm",
    "python3",
]
_MIN_PYTHON_MAJOR = 3
_MIN_PYTHON_MINOR = 6
_MIN_RPM_MAJOR = 4
_MIN_RPM_MINOR = 14


def check_requirements() -> List[str]:
    """
    Try to import each requirement of the giso tool suite, returning any that
    are not available.

    :returns:
        List of missing requirements

    """
    missing_deps: List[str] = []

    for module in _REQUIRED_MODULES:
        try:
            importlib.import_module(module)
        except ImportError:
            missing_deps.append(module)

    for exc in _REQUIRED_EXCS:
        if shutil.which(exc) is None:
            missing_deps.append(exc)

    if (
        sys.version_info.major < _MIN_PYTHON_MAJOR
        or sys.version_info.minor < _MIN_PYTHON_MINOR
    ):
        missing_deps.append(
            "python >= {}.{}".format(_MIN_PYTHON_MAJOR, _MIN_PYTHON_MINOR)
        )
    if "rpm" not in missing_deps:
        missing_rpm = False
        try:
            proc = subprocess.run(
                ["rpm", "--version"],
                stdout=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
        except subprocess.CalledProcessError:
            missing_rpm = True
        else:
            match = re.match(
                r"RPM version (?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)",
                proc.stdout,
            )
            if match is None:
                missing_rpm = True
            elif int(match.group("major")) < _MIN_RPM_MAJOR:
                missing_rpm = True
            elif (
                int(match.group("major")) == _MIN_RPM_MAJOR
                and int(match.group("minor")) < _MIN_RPM_MINOR
            ):
                missing_rpm = True

        if missing_rpm:
            missing_deps.append(
                "rpm >= {}.{}".format(_MIN_RPM_MAJOR, _MIN_RPM_MINOR)
            )

    return missing_deps


def main() -> None:
    """
    Tries to import the various dependencies that are used by
    giso/src/lnt/builder, printing any that are not available

    """
    missing_deps = check_requirements()
    if missing_deps:
        print(", ".join(missing_deps))


if __name__ == "__main__":
    main()
