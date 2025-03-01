# -----------------------------------------------------------------------------

""" Wrapper to launch the GISO build either natively or in a container.

Copyright (c) 2022-2023 Cisco and/or its affiliates.
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

__all__ = ("launch_build",)


import argparse
import logging

from .. import gisoutils

logger = logging.getLogger("gisobuild")


def launch_build(cli_args: argparse.Namespace) -> None:
    """Launch the GISO build."""
    from .. import builder

    gisoutils.add_wrappers_to_path()

    builder.run(cli_args)
