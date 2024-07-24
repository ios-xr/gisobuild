# -----------------------------------------------------------------------------

""" Module providing a wrapper around the subprocess module to run commands.

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

__all__ = ("CalledProcessError", "execute", "execute_combined_stdout")


import logging
import subprocess

# Re-export this so that users don't have to import subprocess as well as out
# aim is to wrap it.
from subprocess import CalledProcessError
from typing import Sequence

_logger = logging.getLogger(__name__)


def _execute_internal(
    cmd: Sequence[str],
    *,
    combined_stdout: bool = True,
    verbose_logging: bool = True
) -> str:
    """
    Internal function to execute a subprocess with sensible options.

    :param cmd:
        The command to execute.

    :param combined_stdout:
        Boolean indicating whether to combine the stdout and stderr streams
        into one. Defaults to True, otherwise separate pipes are used.

    :param verbose_logging:
        Boolean indicating whether to write verbose logs of the command being
        run and successful output.

    :return:
        The stdout of the subprocess.

    """
    stdout = subprocess.PIPE
    if combined_stdout:
        stderr = subprocess.STDOUT
        output_attr = "stdout"
    else:
        stderr = subprocess.PIPE
        output_attr = "stderr"

    if verbose_logging:
        _logger.debug("Running command: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd, check=True, encoding="utf-8", stdout=stdout, stderr=stderr,
        )
    except subprocess.CalledProcessError as e:
        _logger.debug(
            "Command %s failed with exit code %d", " ".join(cmd), e.returncode
        )
        out_lines = getattr(e, output_attr)
        if out_lines is not None:
            for line in getattr(e, output_attr).splitlines():
                _logger.debug("%s: %s", output_attr, line)
        raise
    else:
        if verbose_logging:
            _logger.debug("Command successful.")
            for line in proc.stdout.splitlines():
                _logger.info("stdout: %s", line)

    return proc.stdout


def execute(cmd: Sequence[str], verbose_logging: bool = True) -> str:
    """
    Run the command as a subprocess capturing the output and adding logs.

    :param cmd:
        Command to run in the subprocess.

    :param verbose_logging:
        Boolean indicating whether to write verbose logs of the command being
        run and successful output.

    :return:
        The stdout from the command if successful.

    """
    return _execute_internal(
        cmd, combined_stdout=False, verbose_logging=verbose_logging
    )


def execute_combined_stdout(
    cmd: Sequence[str], verbose_logging: bool = True
) -> str:
    """
    Run the command as a subprocess combining stdout and stderr streams.

    :param cmd:
        The command to run in the subprocess.

    :param verbose_logging:
        Boolean indicating whether to write verbose logs of the command being
        run and successful output.

    :return:
        The combined stdout and stderr streams from the command if successful.
    """
    return _execute_internal(
        cmd, combined_stdout=True, verbose_logging=verbose_logging
    )
