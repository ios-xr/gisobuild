# -----------------------------------------------------------------------------

""" Tool to co-ordinate the building of the GISO.

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
        gisoutils.set_user_specified_tools(args), "user-specified build tools",
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
