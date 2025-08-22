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

"""Module providing a wrapper around the subprocess module to run commands."""

__all__ = ("CalledProcessError", "execute", "execute_combined_stdout")


import logging
import subprocess

# Re-export this so that users don't have to import subprocess as well as out
# aim is to wrap it.
from subprocess import CalledProcessError
from typing import Sequence, Tuple

_logger = logging.getLogger(__name__)


def _execute_internal(
    cmd: Sequence[str],
    *,
    combined_stdout: bool = True,
    verbose_logging: bool = True
) -> Tuple[str, str]:
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
        The stdout and stderr of the subprocess.

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
            cmd,
            check=True,
            encoding="utf-8",
            stdout=stdout,
            stderr=stderr,
        )
    except subprocess.CalledProcessError as e:
        _logger.debug(
            "Command %s failed with exit code %d", " ".join(cmd), e.returncode
        )
        out_lines = getattr(e, output_attr)
        if out_lines is not None:
            for line in getattr(e, output_attr).splitlines():
                _logger.debug("%s: %s", output_attr, line)
        raise e
    else:
        if verbose_logging:
            _logger.debug("Command successful.")
            for line in proc.stdout.splitlines():
                _logger.info("stdout: %s", line)

    return proc.stdout, proc.stderr


def execute(
    cmd: Sequence[str], verbose_logging: bool = True
) -> Tuple[str, str]:
    """
    Run the command as a subprocess capturing the output and adding logs.

    :param cmd:
        Command to run in the subprocess.

    :param verbose_logging:
        Boolean indicating whether to write verbose logs of the command being
        run and successful output.

    :return:
        The stderr and stdout from the command if successful.

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
    )[0]
