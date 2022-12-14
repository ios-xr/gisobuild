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
import os
import re
import shutil
import subprocess
import sys

from typing import Any, Dict, List, Tuple

try:
    import yaml
except ImportError:
    print("Missing required python module 'yaml'")
    sys.exit(1)

_script_dir = os.path.dirname(os.path.abspath(__file__))

_requirements_yaml = os.path.join(_script_dir, "requirements.yaml")


class RequirementsParsingError(Exception):
    """
    Error raised if an error occurs reading in the requirements.

    """

    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = description

    def __str__(self) -> str:
        return (
            f"Error parsing the requirements YAML ({_requirements_yaml}):"
            f" {self.description}"
        )


def _get_required_modules(requirements: Dict[str, Any]) -> List[str]:
    """
    Parse the requirements to find the list of required python modules.

    :param requirements:
        Requirements as loaded from the requirements YAML.

    :returns:
        List of python module names required by the GISO tools
    """

    modules = requirements.get("python_modules")
    if not isinstance(modules, list):
        raise RequirementsParsingError(
            "Couldn't get list of required python modules"
        )
    if not all(
        isinstance(module, dict) and "name" in module for module in modules
    ):
        raise RequirementsParsingError("Malformed list of python modules")
    module_names = [module["name"] for module in modules]
    if not all(isinstance(name, str) for name in module_names):
        raise RequirementsParsingError("Python module name is not a string")
    return module_names


def _get_required_executables(requirements: Dict[str, Any]) -> List[str]:
    """
    Parse the requirements to find the list of required excutables.

    :param requirements:
        Requirements as loaded from the requirements YAML.

    :returns:
        List of executables required by the GISO tools
    """
    executables = requirements.get("executable_requirements")
    if not isinstance(executables, list):
        raise RequirementsParsingError(
            "Couldn't get list of required executables"
        )
    if not all(
        isinstance(executable, dict) and "name" in executable
        for executable in executables
    ):
        raise RequirementsParsingError("Malformed list of executables")
    executable_names = [
        executable["name"]
        for executable in executables
        if not executable.get("optional", False)
    ]
    if not all(isinstance(name, str) for name in executable_names):
        raise RequirementsParsingError("Executable name is not a string")
    return executable_names


def _get_minimum_python_version(
    requirements: Dict[str, Any]
) -> Tuple[int, int]:
    """
    Parse the requirements to find the minimum required python version.

    :param requirements:
        Requirements as loaded from the requirements YAML.

    :returns:
        Minimum python version as a tuple of (major-version, minor-version)
    """

    executables = requirements.get("executable_requirements")
    if not isinstance(executables, list):
        raise RequirementsParsingError(
            "Couldn't get list of required executables"
        )
    if not all(
        isinstance(executable, dict) and "name" in executable
        for executable in executables
    ):
        raise RequirementsParsingError("Malformed list of executables")

    python_requirement = [
        executable
        for executable in executables
        if executable["name"] == "python3"
    ]
    if not len(python_requirement) == 1:
        raise RequirementsParsingError(
            "Could not find python version requirements"
        )
    if "min_version" not in python_requirement[0]:
        raise RequirementsParsingError("Could not find minimum python version")

    python_version = re.match(
        r"(?P<major>\d+)\.(?P<minor>\d+)",
        python_requirement[0]["min_version"],
    )
    if not python_version:
        raise RequirementsParsingError(
            "Could not parse minimum python version"
        )

    return (
        int(python_version.group("major")),
        int(python_version.group("minor")),
    )


def _get_minimum_rpm_version(requirements: Dict[str, Any]) -> Tuple[int, int]:
    """
    Parse the requirements to find the minimum required rpm version.

    :param requirements:
        Requirements as loaded from the requirements YAML.

    :returns:
        Minimum rpm version as a tuple of (major-version, minor-version)
    """

    executables = requirements.get("executable_requirements")
    if not isinstance(executables, list):
        raise RequirementsParsingError(
            "Couldn't get list of required executables"
        )
    if not all(
        isinstance(executable, dict) and "name" in executable
        for executable in executables
    ):
        raise RequirementsParsingError("Malformed list of executables")

    rpm_requirement = [
        executable for executable in executables if executable["name"] == "rpm"
    ]
    if not len(rpm_requirement) == 1:
        raise RequirementsParsingError(
            "Could not find rpm version requirements"
        )
    if "min_version" not in rpm_requirement[0]:
        raise RequirementsParsingError("Could not find minimum rpm version")

    rpm_version = re.match(
        r"(?P<major>\d+)\.(?P<minor>\d+)", rpm_requirement[0]["min_version"],
    )
    if not rpm_version:
        raise RequirementsParsingError("Could not parse minimum rpm version")

    return (int(rpm_version.group("major")), int(rpm_version.group("minor")))


def check_requirements() -> List[str]:
    """
    Try to import each requirement of the giso tool suite, returning any that
    are not available.

    :returns:
        List of missing requirements

    """
    missing_deps: List[str] = []

    # Load the requirements yaml.  To avoid pulling in extra dependencies
    # into our dependency checker, we don't use the validate module to parse
    # the contents into a dataclass. Instead we just use the raw dictionary and
    # sanity check any contents we need.
    with open(_requirements_yaml) as f:
        requirements: dict[str, Any] = yaml.safe_load(f)
    if not isinstance(requirements, dict):
        raise RequirementsParsingError("Parsed data is not a dictionary")
    if not all(isinstance(key, str) for key in requirements):
        raise RequirementsParsingError(
            "Parsed data is not a dictionary of the expected type"
        )

    for module in _get_required_modules(requirements):
        try:
            importlib.import_module(module)
        except ImportError:
            missing_deps.append(module)

    for exc in _get_required_executables(requirements):
        if shutil.which(exc) is None:
            missing_deps.append(exc)

    min_python_major, min_python_minor = _get_minimum_python_version(
        requirements
    )

    if (
        sys.version_info.major < min_python_major
        or sys.version_info.minor < min_python_minor
    ):
        missing_deps.append(
            "python >= {}.{}".format(min_python_major, min_python_minor)
        )

    min_rpm_major, min_rpm_minor = _get_minimum_rpm_version(requirements)
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
            elif int(match.group("major")) < min_rpm_major:
                missing_rpm = True
            elif (
                int(match.group("major")) == min_rpm_major
                and int(match.group("minor")) < min_rpm_minor
            ):
                missing_rpm = True

        if missing_rpm:
            missing_deps.append(
                "rpm >= {}.{}".format(min_rpm_major, min_rpm_minor)
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
