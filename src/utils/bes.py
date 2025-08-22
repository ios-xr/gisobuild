# -----------------------------------------------------------------------------
# BSD 3-Clause License
#
# Copyright (c) 2024-2025, Cisco Systems, Inc. and its affiliates
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the [organization] nor the names of its contributors
#    may be used to endorse or promote products derived from this software
#    without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# -----------------------------------------------------------------------------

"""GISO logging utilities required for build environment security (BES)."""

__all__ = (
    "enable_logging",
    "log",
    "log_cmd_call",
    "log_env_vars",
    "log_files",
    "log_os_release",
    "log_tools",
)

import argparse
import logging
import os
import pwd
import shutil
import socket
import subprocess
import sys
import time
from typing import Any, Dict, Iterable, List, Optional

from utils import gisoutils

_LOGGER = logging.getLogger("BES")
_LOGGING_ENABLED: bool = False

_INDENT = "  "

# Common CLI arguments that can be used to get the version of a tool.
_VERSION_ARGS = ["--version", "-version", "-v", "version"]

# OS release information file
_OS_RELEASE_FILE = "/etc/os-release"


class BESLoggingError(Exception):
    """Exception for build environment logging errors."""


def _init_logger() -> None:
    """
    Initialize build environment security (BES) logger.

    Adds a handler to the BES logger that writes all logs to stderr with a
    timestamp following the BES requirements.

    """
    formatter = logging.Formatter(
        fmt="%(asctime)s gisobuild: %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ"
    )
    formatter.converter = time.gmtime
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)

    global _LOGGER
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.DEBUG)


def _clean_logger() -> None:
    """Clear the handlers from the BES logger."""
    global _LOGGER
    _LOGGER.handlers.clear()


def _get_sha256_msg(file_path: str) -> str:
    """
    Return a log message with the sha256 hash of the given file.

    :raises BESLoggingError:
        If the sha256 hash of the file cannot be calculated.

    """
    try:
        sha256_hash, _ = gisoutils.get_file_hash_length(file_path)
        return f"sha256: {sha256_hash}"
    except IOError as e:
        raise BESLoggingError(
            f"Failed to calculate sha256 of {file_path}"
        ) from e


def _find_tool_version(tool_path: str) -> Optional[str]:
    """Best effort find of the tool version."""
    for arg in _VERSION_ARGS:
        try:
            return subprocess.check_output(
                [tool_path, arg], stderr=subprocess.DEVNULL
            ).decode()
        except subprocess.CalledProcessError:
            pass
    return None


def log(*args: Any, **kwargs: Any) -> None:
    """
    Write a build environment log, initializing the logger if necessary.

    Accepts the same arguments as logging.info() in the standard python library.

    """
    if _LOGGING_ENABLED:
        _LOGGER.info(*args, **kwargs)


def enable_logging() -> None:
    """Enable build environment security logging to the terminal."""
    global _LOGGING_ENABLED
    _LOGGING_ENABLED = True
    if not _LOGGER.handlers:
        _init_logger()


def disable_logging() -> None:
    """Disable build environment security logging to the terminal."""
    global _LOGGING_ENABLED
    _LOGGING_ENABLED = False
    _clean_logger()


def log_cmd_call(args: argparse.Namespace, yaml_args: Dict[str, Any]) -> None:
    """
    Log the details of the current command invocation to the terminal.

    Logged information:
    - Command line arguments
    - Arguments from the input YAML file
    - User name and ID
    - Host name and address
    - Full path and SHA256 hash of all input files, including ones found in
      any user-specified repo directories.

    Note that the constituents of input tarballs are not logged by this
    function, so must be unpacked and logged separately if needed.

    :param args:
        The parsed arguments from the command line.
    :param yaml_args:
        The parsed arguments from the input YAML file.

    """
    if not _LOGGING_ENABLED:
        return

    # Log the command, user, and host information.
    log("command: %s", " ".join(sys.argv))
    if yaml_args:
        log("yaml args: %s", str(yaml_args))
    uid = os.getuid()
    log("user: %s (%d)", pwd.getpwuid(uid).pw_name, uid)
    hostname = socket.gethostname()
    log("host: %s (%s)", hostname, socket.gethostbyname(hostname))

    # Find all the input files to the build.
    input_files: List[str] = []
    for file_or_dir in gisoutils.get_input_files_and_dirs(args):
        if os.path.isdir(file_or_dir):
            input_files.extend(
                [f.path for f in os.scandir(file_or_dir) if not f.is_dir()]
            )
        else:
            input_files.append(file_or_dir)

    log_files(input_files, "input files")


def log_env_vars(env_vars: Iterable[str]) -> None:
    """
    Log the environment variables used by the build and their values.

    :param env_vars:
        Names of the environment variables to be logged.

    """
    if not _LOGGING_ENABLED:
        return

    env_var_log = []
    for env_var in env_vars:
        value = os.getenv(env_var)
        value_str = ("=" + value) if value else " is not set"
        env_var_log.append(f"{_INDENT}{env_var}{value_str}")
    if env_var_log:
        log(
            "environment variables used by the build:\n%s",
            "\n".join(env_var_log),
        )


def log_os_release() -> None:
    """
    Log the host OS release information.

    :raises BESLoggingError:
        If the host OS release information file cannot be found.

    """
    if not _LOGGING_ENABLED:
        return

    try:
        with open(_OS_RELEASE_FILE, "r") as f:
            os_log = "host operating system:\n"
            for line in f:
                os_log += f"{_INDENT}{line}"
        log(os_log)
    except FileNotFoundError as e:
        raise BESLoggingError(
            f"Failed to find the host OS version file {_OS_RELEASE_FILE}"
        ) from e


def log_tools(tools: Iterable[str], description: str) -> None:
    """
    Log the toolchain used by the build.

    Logged information:
    - Full path (found from the PATH or given paths)
    - SHA256 hash
    - Version information (if available)

    :param tools:
        Tools to be logged. These can be either names that are looked for in
        the PATH, paths relative to the current working directory, or absolute
        paths to the tool.
    :param description:
        Description that precedes the tool information in the log.

    """
    if not _LOGGING_ENABLED:
        return

    tools_info = []
    for tool in tools:
        # Look for the tool in the PATH.
        # Absolute tool paths are returned unchanged if they are found,
        # otherwise None is returned.
        which_output = shutil.which(tool)
        if which_output is None:
            # Some tools are optional, so may or may not be present in the
            # build environment. We should log and continue in this case.
            tools_info.append(f"{_INDENT}could not find {tool} in the PATH")
            continue
        tool_path = os.path.abspath(which_output)
        tools_info.append(f"{_INDENT}{tool_path}:")

        # Find the hash and version information.
        tools_info.append(_INDENT * 2 + _get_sha256_msg(tool_path))
        version = _find_tool_version(tool_path)
        if version is not None:
            tools_info.append(f"{_INDENT * 2}version:")
            for version_line in version.splitlines():
                tools_info.append(f"{_INDENT * 3}{version_line}")
        else:
            # Not all tools have a "--version" argument or equivalent.
            tools_info.append(
                f"{_INDENT * 2}version could not be found using any of "
                f"the following arguments: {', '.join(_VERSION_ARGS)}"
            )

    if tools_info:
        log("%s:\n%s", description, "\n".join(tools_info))


def log_files(files: Iterable[str], description: str) -> None:
    """
    Log the full path and SHA256 hash of a list of files.

    :param files:
        Files to be logged. These can be either paths relative to the
        current working directory or absolute paths to the files.
    :param description:
        Description that precedes the file information in the log.
    """
    if not _LOGGING_ENABLED:
        return

    files_info = []
    for file in files:
        full_path = os.path.abspath(file)
        files_info.append(f"{_INDENT}{full_path}:")
        files_info.append(_INDENT * 2 + _get_sha256_msg(full_path))

    if files_info:
        log("%s:\n%s", description, "\n".join(files_info))
