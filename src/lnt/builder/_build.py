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
import sys


from .. import check_requirements


def _check_requirements() -> None:
    """
    Check that all required python modules and executables are present.
    """
    # Prior to importing the full tool set, check that all requirements are met
    missing_reqs = check_requirements.check_requirements()
    if len(missing_reqs) != 0:
        print(
            "Gisobuild failed: Missing environment requirements {}".format(
                ", ".join(missing_reqs)
            ),
            file=sys.stderr,
        )
        sys.exit(1)


def run(args: argparse.Namespace) -> None:
    """
    Run the golden ISO build.

    :param args:
        parsed arguments

    """
    _check_requirements()
    # Need to import after checking requirements so that we don't import
    # everything else which uses our requirements.
    from . import _coordinate

    sys.exit(_coordinate.run(args))
