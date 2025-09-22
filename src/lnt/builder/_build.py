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

"""Tool to co-ordinate the building of the GISO."""

import argparse
import os.path
import sys
from typing import Any, Dict

from .. import check_requirements


def _check_requirements() -> Dict[str, Any]:
    """
    Check that all required python modules and executables are present.
    """
    # Prior to importing the full tool set, check that all requirements are met
    missing_reqs, full_reqs = check_requirements.check_requirements()
    if len(missing_reqs) != 0:
        print(
            "Gisobuild failed: Missing environment requirements {}".format(
                ", ".join(missing_reqs)
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    return full_reqs


def run(args: argparse.Namespace) -> None:
    """
    Run the golden ISO build.

    :param args:
        parsed arguments

    """
    requirements = _check_requirements()
    # Need to import after checking requirements so that we don't import
    # everything else which uses our requirements.
    from utils import bes, gisoglobals

    from .. import gisoutils
    from . import _coordinate

    # Log the tools used by gisobuild and the image.py script it calls.
    bes.log_tools(
        {t["name"] for t in requirements["executable_requirements"]},
        "default build tools",
    )
    bes.log_tools(
        gisoutils.set_user_specified_tools(args),
        "user-specified build tools",
    )
    bes.log_tools(
        {
            os.environ[e]
            for e in gisoglobals.IMAGE_PY_ENV_VARS
            if e in os.environ
        },
        "user-specified image.py tools",
    )

    sys.exit(_coordinate.run(args))
