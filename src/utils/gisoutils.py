# -----------------------------------------------------------------------------

""" GISO utilities.

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

import shutil
import sys
import os
import logging
from logging import handlers
import datetime
import threading
import time

from typing import (
    Any,
    Union,
    Dict,
)
from . import gisoglobals
from . import _subprocs

logger = logging.getLogger(__name__)
e = threading.Event()


def progressbar() -> None:
    """Display a progress bar on stdout."""
    i = 0
    while not e.is_set():
        sys.stdout.flush()
        if (i % 4) == 0:
            sys.stdout.write("\b/")
        elif (i % 4) == 1:
            sys.stdout.write("\b-")
        elif (i % 4) == 2:
            sys.stdout.write("\b\\")
        elif (i % 4) == 3:
            sys.stdout.write("\b|")
        sys.stdout.flush()
        time.sleep(0.2)
        i += 1


def display_progress() -> None:
    """Display progress of an operation using a background thread."""
    global e
    t1 = threading.Thread(name="blocking", target=progressbar, args=())
    t1.start()
    e.clear()


def stop_progress() -> None:
    """Stop monitoring an operation's progress."""
    global e
    e.set()
    print("\nDone...")


def initialize_console_logging() -> None:
    """Initialize logging INFO messages to console."""
    root_logger = logging.getLogger()
    # Console message
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    root_logger.addHandler(ch)


def create_working_dir(
    out_clean: bool, output_dir: str, module_name: str
) -> None:
    """Set the working directory and logger."""
    out_abs_path = os.path.abspath(output_dir)
    if os.path.exists(output_dir):
        cwd = os.getcwd()
        out_abs_path = os.path.abspath(output_dir)
        if cwd.startswith(out_abs_path):
            raise AssertionError(
                "Cannot use {} as output directory".format(out_abs_path)
            )
        if out_clean:
            shutil.rmtree(output_dir)

    os.makedirs(output_dir)

    LOGDIR = "{}/logs".format(output_dir)
    LOGFILE = "{}/{}.log-{}".format(
        LOGDIR,
        module_name,
        datetime.datetime.now().strftime("%Y-%m-%d:%H:%M:%S.%f"),
    )
    logfile = LOGFILE.format(output_dir=output_dir)

    os.makedirs(LOGDIR)

    # create logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s::  %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    # Logs to logfile
    fh = handlers.RotatingFileHandler(logfile)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    root_logger.addHandler(fh)


def match_file_type(file_att: str) -> str:
    """Match file type against a global list."""
    for f_type, token in gisoglobals.file_types.items():
        if all(map(file_att.__contains__, token)):
            return f_type
    return gisoglobals.FILE_TYPE_UNKNOWN


def get_file_type(filename: str) -> str:
    """Get file type."""
    if not os.path.exists(filename):
        raise AssertionError("{} does not exist.".format(filename))
    cmd = "file -L {}".format(filename)
    output = _subprocs.execute(cmd.split())
    file_att = output.split(":")[1].strip()
    return match_file_type(file_att)


def load_yaml_giso_arguments(yaml_f: str) -> Union[Dict[str, Any], Any]:
    """Load GISO YAML."""

    try:
        import utils.yamlparser as yaml
    except Exception as exc:
        raise AssertionError("Unable to import Yaml module.") from exc
    with open(yaml_f, "r", encoding="utf-8") as fd:
        data = yaml.safe_load(fd)
    if "in_docker" not in data.keys():
        data["in_docker"] = False
    return data


def dump_yaml_giso_arguments(yaml_f: str, data: Dict[str, Any]) -> None:
    """Dump GISO YAML."""

    try:
        import utils.yamlparser as yaml
    except Exception as exc:
        raise AssertionError("Unable to import Yaml module.") from exc
    with open(yaml_f, "w", encoding="utf-8") as fd:
        fd.write(yaml.dump(data))


def is_platform_exr(iso: str) -> bool:
    """Check whether an ISO is eXR or LNT."""

    is_exr = False
    try:
        files_top = _subprocs.execute(
            ["isoinfo", "-i", iso, "-R", "-f"]
        ).splitlines()
        if "/iso_info.txt" in files_top:
            is_exr = True
        elif "/mdata/mdata.json" in files_top:
            is_exr = False
        else:
            raise AssertionError("Input ISO file is not a valid image.")
    except Exception as error:
        raise AssertionError(
            "Failed to determine input ISO image type."
        ) from error

    return is_exr
