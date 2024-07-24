#!/usr/bin/env python3
# ----------------------------------------------------------------

""" Wrapper script to generate a diff between two ISOs.

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

__all__ = ()


import os
import pathlib
import sys

# The use of abspath() is to address an issue with python3.6 where if isols.py
# is run from the directory where the file is located the value of __file__ is
# just ./isols.py rather than an absolute path.
sys.path = [str(pathlib.Path(os.path.abspath(__file__)).parents[1])] + sys.path
from lnt import tools

if __name__ == "__main__":
    tools.isodiff(sys.argv[1:])
