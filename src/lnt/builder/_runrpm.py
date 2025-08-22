# -----------------------------------------------------------------------------
# BSD 3-Clause License
#
# Copyright (c) 2021-2025, Cisco Systems, Inc. and its affiliates
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

"""Module for running various RPM commands as a subprocess."""

__all__ = (
    "CheckInstallError",
    "CheckSignatureError",
    "ImportSignatureKeyError",
    "QueryFormatError",
    "check_install",
    "check_signature",
    "import_key",
    "query_format",
)


import functools
import logging
import os
import pathlib
import subprocess
from typing import Callable, List, Sequence

from utils import subprocs

_logger = logging.getLogger(__name__)


class _BaseError(Exception):
    """
    Base error class for rpm subprocess errors.

    """

    def __init__(
        self, exc: subprocess.CalledProcessError, msg_prefix: str
    ) -> None:
        """
        Initialize the class.

        :param exc:
            The subprocess exception which caused this.

        :param msg_prefix:
            The prefix for the error message.

        """
        super().__init__(exc, msg_prefix)
        self.exc = exc
        self.msg_prefix = msg_prefix

    def __str__(self) -> str:
        return f"{self.msg_prefix}: {str(self.exc)}"


class QueryFormatError(_BaseError):
    """
    Error class for query-format errors.

    """

    def __init__(
        self,
        pkg_path: pathlib.Path,
        exc: subprocess.CalledProcessError,
    ) -> None:
        super().__init__(exc, f"Query of RPM {pkg_path} failed:")


class ImportSignatureKeyError(_BaseError):
    """
    Error class for import key signature errors.

    """

    def __init__(
        self,
        key_file: pathlib.Path,
        exc: subprocess.CalledProcessError,
    ) -> None:
        super().__init__(
            exc, f"Failed to import key '{key_file.name}' to RPM database"
        )


class CheckSignatureError(_BaseError):
    """
    Error class for signature checking failures.

    """

    def __init__(
        self,
        pkg_path: pathlib.Path,
        exc: subprocess.CalledProcessError,
    ) -> None:
        super().__init__(exc, f"Error when checking signatures for {pkg_path}")


class CheckInstallError(_BaseError):
    """
    Error class for checking if the rpms will install.

    """

    def __init__(
        self,
        exc: subprocess.CalledProcessError,
    ) -> None:
        super().__init__(exc, "Error checking if the packages are installable")


def _get_rpm_cmd(args: Sequence[str]) -> List[str]:
    """
    Get RPM command to run.

    If the "--root" option is required and we're not already running as
    root, run in a new user namespace with the current effective user and
    group IDs mapped to the superuser UID and GID in the new namespace.
    This allows rpm to call "chroot()"  when the current effective user
    and group would not otherwise have the capability.
    """
    if "--root" in args and os.getuid() != 0:
        return ["unshare", "-r", "rpm", *args]
    else:
        return ["rpm", *args]


def _run_rpm(
    args: Sequence[str],
    exc_creator: Callable[[subprocess.CalledProcessError], _BaseError],
) -> str:
    """
    Internal helper to run RPM.

    :param args:
        Arguments to pass to the rpm subprocess.

    :param exc_creator:
        Function to create an exception from a subprocess error.

    :return:
        The output from the command if successful.

    """
    cmd = _get_rpm_cmd(args)
    try:
        out = subprocs.execute_combined_stdout(cmd, verbose_logging=False)
    except subprocess.CalledProcessError as e:
        raise exc_creator(e) from e
    return out


def query_format(pkg_path: pathlib.Path, fmt: str) -> str:
    """
    Run a query on the given rpm.

    :param pkg_path:
        The path to the package to run a query on.

    :param fmt:
        The format of the query.

    :raises QueryFormatError:
        If the RPM command failed.

    :return:
        The output from the rpm command.

    """
    _logger.debug("Querying package: %s", str(pkg_path))
    return _run_rpm(
        ["--nosignature", "-qp", str(pkg_path), "--qf", fmt],
        functools.partial(QueryFormatError, pkg_path),
    )


def import_key(db_dir: pathlib.Path, key_file: pathlib.Path) -> str:
    """
    Import the key file into the given RPM database.

    :param db_dir:
        Path to the RPM database directory.

    :param key_file:
        The path to the key file to add to the database.

    :raises ImportSignatureKeyError:
        If the rpm command failed.

    :return:
        The output from the rpm command.

    """
    _logger.debug("Importing key file %s to rpm database", str(key_file))
    return _run_rpm(
        ["--dbpath", str(db_dir), "--import", str(key_file)],
        functools.partial(ImportSignatureKeyError, key_file),
    )


def check_signature(db_dir: pathlib.Path, pkg_path: pathlib.Path) -> str:
    """
    Check the signature of the given package.

    :param db_dir:
        Path to directory of the RPM database.

    :param pkg_path:
        Path to the package to check.

    :raises CheckSignatureError:
        If the rpm command errors.

    :return:
        The output from the rpm command.

    """
    return _run_rpm(
        ["--dbpath", str(db_dir), "-Kv", str(pkg_path)],
        functools.partial(CheckSignatureError, pkg_path),
    )


def check_install(db_dir: pathlib.Path, pkgs: Sequence[pathlib.Path]) -> str:
    """
    Check if the given collection of RPMs will install.

    :param db_dir:
        The directory of the RPM database.

    :param pkgs:
        The packages to check.

    :raises CheckInstallError:
        Raised if the install check fails.

    :return:
        The output from the rpm command.

    """
    _logger.debug("Checking installability of %u packages", len(pkgs))
    return _run_rpm(
        [
            "--nosignature",
            "--install",
            "--test",
            # Don't execute install/uninstall/post uninstall scripts or trigger
            # scriptlets
            "--noscripts",
            "--notriggers",
            # Ignore differences between host arch and package arches (so that
            # darwin doesn't fail)
            "--ignorearch",
            # Ignore differences between host OS and rpm OS. I think the OS is
            # likely to be just "linux" for both host and target rpms but it's
            # best to isolate the checks from the host environment as much as
            # possible.
            "--ignoreos",
            # Ignore size available on this device - we aren't actually
            # installing to this device/partition, so insufficient disk space
            # should not cause this to crash.
            "--ignoresize",
            "--justdb",
            "--dbpath",
            "/",
            # Need to set a root directory because in our docker image /sbin is
            # a symlink to /usr/sbin/ which causes conflicts. Just use the
            # database as the root dir.
            "--root",
            str(db_dir),
            *(str(pkg) for pkg in pkgs),
        ],
        CheckInstallError,
    )
