# -----------------------------------------------------------------------------

""" Launch a GISO build in a container.

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

__all__ = (
    "execute_build",
    "IMAGE_NAME",
    "IMAGE_VERSION",
)


import argparse
import datetime
import glob
import itertools
import logging
import os
import pathlib
import secrets
import shutil
import sys
import tempfile
import types
import typing
from typing import Dict, Iterator, List, NoReturn, Optional, Tuple

from . import bes
from . import gisoglobals as gglobals
from . import gisoutils, subprocs

# This image version *MUST* be updated whenever the built container changes
# (e.g. Dockerfile change).
IMAGE_NAME = gglobals.IMAGE_NAME
IMAGE_VERSION = gglobals.IMAGE_VERSION

logger = logging.getLogger(__name__)
_containertool = "docker"


# Output build artefacts to this location in the container
#
# - Output dir is input to the build script
# - Log dir and artifact dir are calculated by the build script based on the
#   output dir
_CTR_OUT_DIR = gglobals.CTR_OUT_DIR
_CTR_LOG_DIR = gglobals.CTR_LOG_DIR

# incase of eXR gisobuild staging location inside /tmp is failing due to error:
#   "no space left on device"
# so instead of using /tmp we are using the user provided staging location.


def eXR_fix_staging_location(
    cli_args: argparse.Namespace, container: types.ModuleType
) -> None:
    """
    Changes the temporary staging location to a temporary directory
    inside "out_directory" incase of eXR.
    :param cli:
        commandline arguments.
    :param container:
        imported module: gisobuild_docker_exr
    """
    if cli_args.exriso:
        gglobals.CTR_OUT_DIR = tempfile.mkdtemp(dir=cli_args.out_directory)
        global _CTR_OUT_DIR
        _CTR_OUT_DIR = gglobals.CTR_OUT_DIR
        setattr(container, "_CTR_OUT_DIR", gglobals.CTR_OUT_DIR)


def _print_error(line: str) -> None:
    """Print a line of error output."""
    print(line, file=sys.stderr)


def _fatal_error(*msgs: str, prefix: str = "Error: ") -> NoReturn:
    """Exit with an error message."""
    logger.critical("Fatal error: %s", "\n".join(msgs))
    for msg in msgs:
        _print_error(f"{prefix}{msg}")
    sys.exit(1)


def _fatal_error_from_subprocess(
    description: str, error: subprocs.CalledProcessError
) -> NoReturn:
    """
    Exit with an error message derived from a failed subprocess.

    :param description:
        Description of the failed subprocess' purpose, e.g. 'Bridge painter'.
    :param error:
        Error from subprocess.

    """
    cmd = " ".join(error.cmd)
    _fatal_error(
        f"{description} '{cmd}' failed with exit code {error.returncode}",
        *error.stderr.splitlines(),
    )


def _system_resource_check() -> None:
    """
    Checks that the docker tool is available, printing an error if it is not

    """
    global _containertool

    try:
        subprocs.execute([_containertool, "info"], verbose_logging=False)
    except (subprocs.CalledProcessError, FileNotFoundError):
        try:
            # If docker isn't available, try podman
            _containertool = "podman"
            subprocs.execute([_containertool, "info"], verbose_logging=False)
        except (subprocs.CalledProcessError, FileNotFoundError):
            _fatal_error(
                "Enable docker or podman service to allow container pull and run."
            )

    logger.debug("Found working container tool: %s", _containertool)


def unify_staging(
    cli_args: argparse.Namespace,
) -> typing.Optional[tempfile.TemporaryDirectory]:  # type: ignore
    """
    Aggregates package files from multiple repo(s) into one location and sets
    correct access rights inorder to make it accessible inside docker container.
    """
    unified_staging = None
    # {pkgname: pkg_filepath}
    unified_pkgs = {}
    for repo in cli_args.repo:
        repo = os.path.normpath(repo)
        logger.info("Scanning: %s", repo)
        acceptable_file_extentions = ["rpm", "tar", "tgz"]
        for ext in acceptable_file_extentions:
            for r_file in glob.glob(os.path.join(repo, f"*.{ext}")):
                unified_pkgs.update({os.path.basename(r_file): r_file})

    if len(unified_pkgs):
        unified_staging = tempfile.TemporaryDirectory(
            prefix="UNIFIED_REPO-", dir=cli_args.out_directory
        )
        for file_path in unified_pkgs.values():
            if os.access(file_path, os.R_OK):
                logger.debug("READ ACCESS: %s [OK]", file_path)
                logger.debug(
                    "Copying: %s to %s", file_path, unified_staging.name
                )
                shutil.copy(file_path, unified_staging.name)
                os.chmod(
                    os.path.join(
                        unified_staging.name, os.path.basename(file_path)
                    ),
                    0o777,
                )
            else:
                logger.warning("READ ACCESS: %s [FAILED]", file_path)
    if unified_staging:
        cli_args.repo.clear()
        cli_args.repo.append(unified_staging.name)
    return unified_staging


def _get_volumes_to_mount(args: argparse.Namespace, infile: str) -> List[str]:
    """
    Mount the volumes required by the arguments into the container

    :param args:
        The arguments provided to the unified giso build script

    :param infile:
        Path to the yamlfile containing the arguments

    :returns:
        The list of the volumes that will need to be mounted when making the
        ISO

    """

    vol_map_list: List[str] = []

    dirname = os.path.dirname(infile)
    vol_map_list.append(os.path.normpath(dirname))

    vol_map_list.extend(
        os.path.normpath(f)
        for f in gisoutils.get_input_files_and_dirs(args)
        if os.path.exists(f)
    )

    if args.optimize:
        o_path = pathlib.Path(__file__).parents[3] / "exr"
        if str(o_path) not in sys.path:
            sys.path.append(str(o_path))
        import exr  # pylint: disable=import-error

        vol_map_list.extend(exr.VOLUMES)

    for env_var in gglobals.IMAGE_PY_ENV_VARS:
        if env_var in os.environ:
            image_py_tool = os.path.abspath(os.environ[env_var])
            if os.path.exists(image_py_tool):
                vol_map_list.append(image_py_tool)

    return list(set(vol_map_list))


def _stage_artefacts(
    out_dir: pathlib.Path,
    container_name: str,
) -> pathlib.Path:
    """
    Stage build artefacts from container

    :param out_dir:
        Output directory in input.

    :param container_name:
        Name of the container.

    Returns the staging location where logs and built artefacts are staged.

    """
    tmp_dir = tempfile.mkdtemp(dir=out_dir)
    try:
        subprocs.execute(
            [
                _containertool,
                "cp",
                f"{container_name}:{_CTR_OUT_DIR}",
                tmp_dir,
            ],
            verbose_logging=False,
        )
    except subprocs.CalledProcessError as error:
        raise RuntimeError(
            "Unable to stage container built artefacts."
        ) from error

    logger.debug("Build artefacts staged to temporary dir %s", tmp_dir)
    return pathlib.Path(tmp_dir)


def _get_image_tags(desired_name: str) -> Iterator[Tuple[str, str]]:
    """
    Yield name, tag (aka version) pairs for images with the given name.

    The name is the fully-qualified name returned by the images command; i.e.
    including host.

    """
    images, _ = subprocs.execute(
        [
            _containertool,
            "images",
            "--format",
            "{{.Repository}} {{.Tag}}",
            desired_name,
        ],
        verbose_logging=False,
    )

    for line in images.splitlines():
        qualified_name, tag = line.split()
        name = qualified_name.rsplit("/", maxsplit=1)[-1]
        if name == desired_name:
            yield qualified_name, tag


def _pull_image(name: str, tag: str) -> None:
    """Pull container image from hub with the given name and tag."""
    try:
        giso_pull_cmd = []
        giso_pull_cmd.extend([_containertool, "pull", f"{name}:{tag}"])
        subprocs.execute(giso_pull_cmd, verbose_logging=False)
    except subprocs.CalledProcessError as error:
        logger.warning("\nCould not pull published docker image.")
        raise RuntimeError("Can't pull Docker image.") from error
    except Exception as error:
        logger.warning(
            "\nUnhandled error while pulling published docker image."
        )
        raise RuntimeError("Can't pull Docker image.") from error


def _build_image(name: str, tag: str, context_dir: str) -> None:
    """Build a container image with the given name and tag."""
    try:
        subprocs.execute(
            [
                _containertool,
                "build",
                "-q",
                "--build-arg",
                "HTTP_PROXY",
                "--build-arg",
                "HTTPS_PROXY",
                "-t",
                f"{name}:{tag}",
                context_dir,
            ]
        )
    except subprocs.CalledProcessError as error:
        _fatal_error_from_subprocess("Container build", error)


def _find_dockerfile() -> pathlib.Path:
    """Return the path to our Dockerfile."""
    path = pathlib.Path(os.path.abspath(__file__)).parents[2] / "Dockerfile"
    if not path.exists():
        raise RuntimeError(
            "Can't find Dockerfile to build a container image, "
            f"looked here: '{path}'"
        )
    return path


def _ensure_image() -> str:
    """
    Ensure that there's a container image for the build.

    If there's already a matching image (identified by name & tag), use that.

    If there's any image with a matching name but different tag, remove it.
    This obviously assumes that it was created by a previous version of this
    tool.

    If there is no matching image, pull one.

    Returns the identifier (`name:tag`) that can be used to refer to the image
    in e.g. a `run` command.

    """
    images = list(_get_image_tags(IMAGE_NAME))
    tags = set(tag for _, tag in images)
    dead_tags = set(tags)
    imgrepo = "ciscogisobuild"
    imgname = f"{imgrepo}/{IMAGE_NAME}"

    if IMAGE_VERSION in tags:
        logger.info("Reuse matching image, %s:%s", IMAGE_NAME, IMAGE_VERSION)
        dead_tags.discard(IMAGE_VERSION)
    else:
        try:
            logger.info("No matching image, pull new image")
            gisoutils.display_progress()
            _pull_image(imgname, IMAGE_VERSION)
            gisoutils.stop_progress()
        except RuntimeError:
            logger.info(
                "\nCould not pull published docker image. build new image"
            )
            try:
                gisoutils.display_progress()
                _build_image(
                    imgname, IMAGE_VERSION, str(_find_dockerfile().parent)
                )
            finally:
                gisoutils.stop_progress()

    # Remaining tags don't match what we want; kill them.
    if dead_tags:
        logger.info(
            "Removing 'old' images with versions: %s",
            ", ".join(sorted(dead_tags)),
        )
        try:
            subprocs.execute(
                [_containertool, "rmi"]
                + [
                    f"{name}:{tag}" for name, tag in images if tag in dead_tags
                ],
                verbose_logging=False,
            )
        except subprocs.CalledProcessError:
            # Best-effort. Images might be in use.
            pass

    return f"{imgname}:{IMAGE_VERSION}"


def _gen_container_name() -> str:
    """Generate a (sufficiently-)random container name."""
    return "giso-{}".format(secrets.token_hex(12))


def _build_giso(
    args: argparse.Namespace, infile: str, container_name: str, image: str
) -> Tuple[str, str]:
    """
    Execute the GISO build.

    On success returns stdout and stderr from the build.

    :param args:
        Parsed CLI args.
    :param infile:
        Path to YAML version of the args.
    :param container_name:
        Name of the container to launch.
    :param image:
        Name and tag of the image to use.

    """
    if args.optimize:
        # We mount the tool one label up instead of 'src' so as to expose
        # signing tools to the gisobuild script.
        src_dir = _find_dockerfile().parents[1]
        o_path = pathlib.Path(__file__).parents[3] / "exr"
        if str(o_path) not in sys.path:
            sys.path.append(str(o_path))
        import exr  # pylint: disable=import-error

        return exr.runCubesGISOBuild(src_dir.__str__(), infile, args)

    src_dir = _find_dockerfile().parent / "src"
    giso_build_cmd = []
    giso_build_cmd.extend([_containertool, "run", "--name", container_name])
    giso_build_cmd.extend(["-v", f"{str(src_dir)}:/app/gisobuild:ro"])
    giso_build_cmd.extend(
        itertools.chain.from_iterable(
            ["-v", f"{vol}:{vol}:ro"]
            for vol in _get_volumes_to_mount(args, infile)
        )
    )
    if args.exriso:
        giso_build_cmd.extend(get_exr_env_vars())
    else:
        giso_build_cmd.extend(get_lnt_env_vars())
    giso_build_cmd.extend(
        [image, "/app/gisobuild/gisobuild.py", "--yamlfile", infile]
    )
    try:
        logger.debug(giso_build_cmd)
        stdout, stderr = subprocs.execute(
            giso_build_cmd, verbose_logging=False
        )
    except subprocs.CalledProcessError as error:
        if args.bes_logging:
            bes.enable_logging()
            bes.log("GISO Build Failed")
        _fatal_error_from_subprocess("GISO build", error)
    return stdout, stderr


def _canonical_path(path: Optional[str]) -> Optional[pathlib.Path]:
    """
    Turn a maybe-relative path into a fully resolved absolute path.

    If the input is `None`, the output is `None`.

    """
    if path is None:
        return None
    else:
        return pathlib.Path(path).resolve()


def _get_current_datetime_as_str() -> str:
    """
    Return the current date & time formatted as a string.

    The result is suitable for use in file/directory names.

    """
    return datetime.datetime.now().strftime("%y%m%d-%H%M%S-%f")


def _main(
    container_name: str, args: argparse.Namespace, infile: str, image: str
) -> None:
    """
    Main function. Set up the required volumes before running the build command
    in the container, finally copying out the produced files.

    :param container_name:
        Name of the container to launch.

    :param args:
        The arguments provided to the unified giso build script

    :param infile:
        Path to the yamlfile containing the arguments

    :param image:
        Name and tag of the image to use.

    """
    is_exrbuild: bool = args.exriso
    args.__dict__ = gisoutils.load_yaml_giso_arguments(infile)
    args.__dict__["exriso"] = is_exrbuild
    stdout, stderr = _build_giso(args, infile, container_name, image)
    # For eXR, debug until we see 'System req...' and once we see that line,
    # we print all subsequent lines to the console. This is done to avoid
    # printing unnecessary info to the console.
    print_to_console: bool = not is_exrbuild
    for line in stdout.splitlines():
        if "System requirements check" in line:
            print_to_console = True
        if line:
            if print_to_console:
                logger.info(line)
            else:
                logger.debug(line)

    # Print the stderr to the console when BES logging is enabled. This
    # includes any errors raised by gisobuild and the build environment logs.
    # All other logs are redirected to stdout for containerized builds.
    if args.bes_logging and stderr:
        print(stderr, file=sys.stderr)


def _execute_build(cli_args: argparse.Namespace) -> None:

    img_dir = None
    if cli_args.exriso:
        from exrmod import gisobuild_docker_exr as container
    else:
        from lnt.launcher import _container as container  # type: ignore

    eXR_fix_staging_location(cli_args, container)

    logger.debug("Running with: %s", cli_args)

    system_resource_check = _system_resource_check
    system_build_prep_env = container.system_resource_prep
    system_build_main = _main

    out_dir = _canonical_path(cli_args.out_directory)
    # Output directory is mandatorily populated.
    assert out_dir is not None
    log_dir = out_dir / _CTR_LOG_DIR / _get_current_datetime_as_str()
    copy_dir = _canonical_path(cli_args.copy_directory)
    system_resource_check()
    unified_repo = unify_staging(cli_args)
    infile = system_build_prep_env(cli_args)
    logger.info("Setting up container environment...")
    image = _ensure_image()
    logger.info("Container Image: %s", image)
    container_name = _gen_container_name()
    try:
        container.setup_copy_out_directory(cli_args)
        logger.info("\nRunning GISO build...")
        gisoutils.display_progress()
        system_build_main(container_name, cli_args, infile, image)
    except Exception:
        logger.exception("\nGiso Build failed. Stage error logs if available.")
    finally:
        gisoutils.stop_progress()
        if unified_repo:
            unified_repo.cleanup()
        try:
            if not cli_args.optimize:
                img_dir = _stage_artefacts(out_dir, container_name)
                subprocs.execute(
                    [_containertool, "rm", "-f", container_name],
                    verbose_logging=False,
                )
        except RuntimeError:
            _fatal_error("GISO build failed. Nothing to stage.")
        except subprocs.CalledProcessError:
            pass

    try:
        if img_dir:
            _CTR_OUTPUT_DIR = os.path.basename(_CTR_OUT_DIR)
            src_dir = pathlib.Path(os.path.join(img_dir, _CTR_OUTPUT_DIR))
            container.copy_artefacts(src_dir, log_dir, out_dir, copy_dir)
    except Exception:
        logger.exception("Exiting with an unhandled error:")
        logger.warning(
            "Unable to copy build artefacts to " "specified output directory."
        )

    shutil.rmtree(os.path.dirname(infile), ignore_errors=True)
    shutil.rmtree(str(img_dir), ignore_errors=True)


def execute_build(args: argparse.Namespace) -> None:
    """Execute build and handle exceptions."""
    try:
        _execute_build(args)
    except subprocs.CalledProcessError as exc:
        # Will have already done detailed logging in our subprocess.run
        # wrapper.
        logger.exception("Exiting with an unhandled subprocess error:")
        msgs = []
        msgs.append(
            f"""GISO build failed: '{" ".join(exc.cmd)}' """
            f"failed with exit code {exc.returncode}"
        )
        if exc.stderr is not None:
            msgs.extend(
                f"error output: {line}" for line in exc.stderr.splitlines()
            )
        _fatal_error(*msgs, prefix="")
    except Exception as exc:
        logger.exception("Exiting with an unhandled error:")
        _fatal_error(f"GISO build failed: {str(exc)}", prefix="")


def _build_optim_image() -> str:
    """
    builds a docker image for optimized gisobuild for eXR platforms and returns
    the name:tag of the image.
    """
    o_path = pathlib.Path(__file__).parents[3] / "exr"
    if str(o_path) not in sys.path:
        sys.path.append(str(o_path))
    import exr  # pylint: disable=import-error

    return exr.build_optim_image()


def _pull_signing_env(cli_args: argparse.Namespace) -> str:
    """
    Create the signing environment used for sign the image.
    """
    o_path = pathlib.Path(__file__).parents[3] / "exr"
    if str(o_path) not in sys.path:
        sys.path.append(str(o_path))
    import exr  # pylint: disable=import-error

    return exr.pull_signing_env(cli_args)


def _get_env_vars() -> Dict[str, str]:
    o_path = pathlib.Path(__file__).parents[3] / "exr"
    if str(o_path) not in sys.path:
        sys.path.append(str(o_path))
    import exr  # pylint: disable=import-error

    return exr.ENV_VARS


def get_exr_env_vars() -> List[str]:
    """
    Container CLI arguments for Lindt specific env variables.

    If the path is not accesible inside the container, mount the path at
    appropriate location.
    """
    extra_args = []
    if "MATRIX_INFO_PATH" in os.environ:
        mtrix_file = pathlib.Path(str(os.environ["MATRIX_INFO_PATH"]))
        logger.info("Using custom compatibility matrix: %s", mtrix_file)
        extra_args.extend(
            ["-v", f"{mtrix_file}:/app/matrix_info_path/upgrade_matrix/:ro"]
        )
        extra_args.extend(
            ["-e", "MATRIX_INFO_PATH=/app/matrix_info_path/upgrade_matrix/"]
        )
    return extra_args


def get_lnt_env_vars() -> List[str]:
    """Container CLI arguments for Lindt specific env variables."""
    extra_args = []
    for env_var in gglobals.LNT_ENV_VARS:
        extra_args.extend(["-e", env_var])
    return extra_args
