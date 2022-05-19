# -----------------------------------------------------------------------------

""" API towards eXR gisobuild launcher.

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

import os
import logging
import sys

def execute_build (cli_args):
    if not cli_args.docker:
        from exrmod import gisobuild_exr
        os.chdir (cli_args.out_directory)
        system_resource_check = gisobuild_exr.system_resource_check
        system_build_prep_env = gisobuild_exr.system_resource_prep
        system_build_main = gisobuild_exr.main
    else: 
        from exrmod import gisobuild_docker_exr
        system_resource_check = gisobuild_docker_exr.system_resource_check
        system_build_prep_env = gisobuild_docker_exr.system_resource_prep
        system_build_main = gisobuild_docker_exr.main

    system_resource_check (cli_args)
    infile = system_build_prep_env (cli_args)
    system_build_main (cli_args, infile)


