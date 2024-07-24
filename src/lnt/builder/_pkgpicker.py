# -----------------------------------------------------------------------------

""" Provides APIs for picking which packages to include in the GISO.

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

__all__ = (
    "AddPkgAction",
    "BaseAction",
    "RemovePkgAction",
    "compare_versions",
    "determine_output_actions",
    "pick_installable_pkgs",
)


import abc
import dataclasses
import logging
import pathlib
import re
import sys
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Pattern,
    Sequence,
    Tuple,
    TypeVar,
)

from . import _blocks, _file, _isoformat, _packages, _subprocs

_log = logging.getLogger(__name__)


class HighestPkgVersionError(Exception):
    """
    Error raised if highest_pkg_version.py errors.

    """

    def __init__(self, cmd: List[str], output: str) -> None:
        super().__init__(cmd, output)
        self.cmd = cmd
        self.output = output

    def __str__(self) -> str:
        return (
            "Unable to determine highest version of packages. Command "
            f"output: {self.output}"
        )


def _run_highest_pkg_version(
    evrs: Sequence[Tuple[str, str, str]]
) -> Tuple[str, str, str]:
    """
    Run the highest_pkg_version script.

    :param evrs:
        Sequence of epoch, version, release tuples to pass to the script.

    :raises HighestPkgVersionError:
        Raised if the script errors.

    :return:
        Epoch, version, release tuple for the highest version.

    """
    script_path = pathlib.Path(__file__).parent / "_highest_pkg_version.py"
    evr_inputs = [",".join(evr) for evr in evrs]
    cmd = [sys.executable, str(script_path), *evr_inputs]
    _log.debug(
        "Determining highest package version with command: '%s'", " ".join(cmd)
    )
    try:
        output = _subprocs.execute_combined_stdout(cmd)
    except _subprocs.CalledProcessError as exc:
        raise HighestPkgVersionError(cmd, exc.output) from exc

    e, v, r = output.strip("\n").split(",")
    return e, v, r


def highest_version(*versions: _packages.EVRA) -> _packages.EVRA:
    """
    Get the highest version from a collection of package versions.

    :param versions:
        Collection of package versions to compare.

    :return:
        The highest member of versions.

    """
    evrs = [(ver.epoch, ver.version.version, ver.release) for ver in versions]
    highest_evr = _run_highest_pkg_version(evrs)
    return versions[evrs.index(highest_evr)]


def compare_versions(ver1: _packages.EVRA, ver2: _packages.EVRA) -> int:
    """
    Compare two versions (as EVRA objects) and return the latest

    :param ver1:
        Version to compare

    :param ver2:
        Version to compare

    :returns int:
        > 0 if ver1 newer, 0 for equal, < 0 if ver2 newer

    """
    if ver1 == ver2:
        return 0
    else:
        highest_evra = highest_version(ver1, ver2)
        if highest_evra == ver1:
            return 1
        else:
            assert highest_evra == ver2
            return -1


_BlockType = TypeVar("_BlockType", _blocks.Block, _blocks.TieBlock)


def _highest_block_version(
    blocks_: Mapping[_packages.EVRA, _BlockType]
) -> _BlockType:
    """
    Get the block with the highest EVR from the given collection of blocks.

    :param blocks_:
        List of blocks to determine the highest version from. Either a
        list of :class:`._blocks.Block` or :class:`._blocks.TieBlock`.

    :return:
        The block with the highest EVR.

    """
    highest_evra = highest_version(*blocks_.keys())
    return blocks_[highest_evra]


class MultipleMatchingBlocksError(Exception):
    """
    Error when multiple block versions match against the package filenames to
    include in the output GISO.

    """

    def __init__(
        self,
        matching_blocks: Iterable[_blocks.AnyBlock],
        add_pkg_filenames: Sequence[str],
    ) -> None:
        super().__init__(matching_blocks, add_pkg_filenames)
        self.matching_blocks = list(matching_blocks)
        self.add_pkg_filenames = add_pkg_filenames

    def __str__(self) -> str:
        name = self.matching_blocks[0].name
        versions = ", ".join(str(block.evra) for block in self.matching_blocks)
        files = ", ".join(self.add_pkg_filenames)
        return (
            f"Block {name} has multiple versions ({versions}) containing "
            "packages that match against the specified files to include: "
            f"{files}"
        )


def _get_block_matching_filenames(
    candidates: Sequence[_BlockType], add_pkg_filenames: Sequence[str]
) -> Optional[_BlockType]:
    """
    Get the block that contains a package matching the given filenames.

    :param candidates:
        The candidate blocks to match against.

    :param add_pkg_filenames:
        The list of filenames to match with.

    :raises MultipleMatchingBlocksError:
        If the exact filenames match against multiple versions of this block.

    :return:
        The matching block or None if there are no matches.

    """
    # If there are no filenames specified then return early without a match.
    if not add_pkg_filenames:
        return None

    matching_blocks = []
    for block in candidates:
        pkg_filenames = set(pkg.filename for pkg in block.all_pkgs)
        matching_filenames = set(add_pkg_filenames) & pkg_filenames
        if matching_filenames and block not in matching_blocks:
            _log.debug(
                "Block %s-%s matches the following package filenames: %s",
                block.name,
                str(block.evra),
                ", ".join(sorted(matching_filenames)),
            )
            matching_blocks.append(block)
    if not matching_blocks:
        # If there are no matches then the user hasn't tried to pick this block
        # at a particular version so just pick the highest version of our
        # candidate blocks.
        return None
    elif len(matching_blocks) > 1:
        # If we match more than one of our candidate blocks then this is user
        # error. The user has provided filenames that match against more than
        # one version of a block which isn't allowed.
        raise MultipleMatchingBlocksError(matching_blocks, add_pkg_filenames)
    else:
        # Otherwise, return the exactly matching block.
        return matching_blocks.pop()


def _match_regexes(
    candidate: _blocks.AnyBlock, regexes: Sequence[Pattern[str]]
) -> bool:
    """
    Match regexes against the candidate block.

    :param candidate:
        The block to match against.

    :param regexes:
        The regexes to match with.

    :return:
        True if any packages in the block match against regexes. False
        otherwise.

    """
    for regex in regexes:
        pkg_name = candidate.top_pkg.name
        match = regex.search(pkg_name)
        if match is not None:
            _log.debug(
                "Block %s-%s matches package regex %s",
                candidate.name,
                str(candidate.evra),
                regex,
            )
            return True
    return False


def _get_block_matching_regexes(
    candidates: Mapping[_packages.EVRA, _BlockType],
    add_pkg_res: Sequence[Pattern[str]],
) -> Optional[_BlockType]:
    """
    Get the version of the block that contains packages matching the regexes.

    If more than one block matches the regexes then the block of the highest
    version is chosen.

    :param candidates:
        The candidate blocks to match against.

    :param add_pkg_res:
        The list of regular expressions to match with.

    :return:
        The matching block of the highest version or None if there are no
        matches.

    """
    matching_blocks = dict()
    for evra, block in candidates.items():
        if _match_regexes(block, add_pkg_res):
            matching_blocks[evra] = block

    if not matching_blocks:
        return None
    else:
        return _highest_block_version(matching_blocks)


def _choose_block_in_iso(
    candidates: Mapping[_packages.EVRA, _BlockType],
    add_pkg_filenames: Sequence[str],
) -> _BlockType:
    """
    Choose the version of the block if the block is in the input iso.

    :param candidates:
        Candidate blocks to choose from.

    :param add_pkg_filenames:
        List of package filenames to include specified on the CLI.

    :return:
        The block to include or None if the block shouldn't be included.
    """
    # If we don't have any filenames to match against then just return early,
    # picking the block at the highest version.
    if not add_pkg_filenames:
        return _highest_block_version(candidates)

    # Find any blocks containing a package which matches against any of the
    # given filenames.
    #
    # Users can specify exact filenames to choose a lower version of a block if
    # they want to downgrade. Match these user-specified filenames against the
    # block packages and choose that specific block if we've got a match.
    #
    # If there are no matches then the user hasn't tried to pick this block at
    # a particular version so just pick the highest version of our candidate
    # blocks.
    matching_block = _get_block_matching_filenames(
        list(candidates.values()), add_pkg_filenames
    )

    if matching_block is not None:
        return matching_block
    else:
        # If there are no matches then the user hasn't tried to pick this block
        # at a particular version so just pick the highest version of our
        # candidate blocks.
        return _highest_block_version(candidates)


def _choose_block_not_in_iso(
    candidates: Mapping[_packages.EVRA, _BlockType],
    add_pkg_filenames: Sequence[str],
    add_pkg_res: Sequence[Pattern[str]],
) -> Optional[_BlockType]:
    """
    Choose the version of the block if the block is not in the input iso.

    :param candidates:
        Candidate blocks to choose from.

    :param add_pkg_filenames:
        List of package filenames to include specified on the CLI.

    :param add_pkg_res:
        List of regular expressions for packages to include specified on the
        CLI.

    :return:
        The block to include or None if the block shouldn't be included.

    """
    # First match against filenames and then only match against regexes if we
    # don't have a filename match.
    matching_block = _get_block_matching_filenames(
        list(candidates.values()), add_pkg_filenames
    )
    if matching_block is not None:
        return matching_block
    else:
        return _get_block_matching_regexes(candidates, add_pkg_res)


def _split_add_pkg_patterns(
    patterns: Sequence[str],
) -> Tuple[List[str], List[Pattern[str]]]:
    """
    Split the "add package patterns" into filepaths and regexes.

    :param patterns:
        List of patterns specified by the user for packages to add. Either
        package names or full .rpm filenames.

    :return:
        A tuple of two elements:
         - list of patterns that are explicit filenames
         - list of compiled regex patterns

    """
    filenames = []
    res = []
    for pattern in patterns:
        if pattern.endswith(".rpm"):
            filenames.append(pattern)
        else:
            res.append(re.compile(pattern))
    return filenames, res


def _add_blocks(
    additional_pkgs_blocks: Dict[str, Dict[_packages.EVRA, _BlockType]],
    iso_pkgs_blocks: Dict[str, Dict[_packages.EVRA, _BlockType]],
    output_pkgs: _blocks.GroupedPackages,
    add_pkg_filenames: Sequence[str],
    add_pkg_res: Sequence[Pattern[str]],
) -> None:
    """
    Add blocks to the output.

    :param additional_pkgs_blocks:
        The blocks from the additional package (repos) specified on the CLI.

    :param iso_pkgs_blocks:
        The blocks from the input ISO.

    :param output_pkgs:
        The collection of packages for the output GISO. Packages are chosen and
        added to this.

    :param add_pkg_filenames:
        Filenames passed on the CLI for additional packages to add.

    :param add_pkg_res:
        Regexes passed on the CLI for additional packages to add.

    """
    for name, block_versions in iso_pkgs_blocks.items():
        if name not in additional_pkgs_blocks:
            for block in block_versions.values():
                output_pkgs.add_block(block)

    for name, block_versions in additional_pkgs_blocks.items():
        if name in iso_pkgs_blocks:
            chosen_block = _choose_block_in_iso(
                {**block_versions, **iso_pkgs_blocks[name]}, add_pkg_filenames,
            )
            output_pkgs.add_block(chosen_block)
        else:
            chosen_block_not_in_iso = _choose_block_not_in_iso(
                block_versions, add_pkg_filenames, add_pkg_res,
            )

            if chosen_block_not_in_iso is not None:
                output_pkgs.add_block(chosen_block_not_in_iso)

    # @@@ Need to better handle loading a GISO that already has cust RPMs in


def _remove_blocks(
    output_pkgs: _blocks.GroupedPackages, remove_pkgs: Sequence[str],
) -> None:
    """
    Remove blocks from the output.

    :param output_pkgs:
        The collection of packages in the output GISO to remove packages from.

    :param remove_pkgs:
        Packages to remove from the ISO.

    """
    handled_remove_pkgs = set()
    for block in output_pkgs.all_blocks:
        if block.name in remove_pkgs:
            _log.debug("%s in list of blocks to remove", block)
            output_pkgs.remove_block(block)
            handled_remove_pkgs.add(block.name)

    for pkg in output_pkgs.all_owner_pkgs:
        if pkg.name in remove_pkgs:
            _log.debug("Owner pkg %s in list of blocks to remove", pkg)
            output_pkgs.remove_owner_pkg(pkg)
            handled_remove_pkgs.add(pkg.name)

    for pkg in output_pkgs.all_partner_pkgs:
        if pkg.name in remove_pkgs:
            _log.debug("Partner pkg %s in list of blocks to remove", pkg)
            output_pkgs.remove_partner_pkg(pkg)
            handled_remove_pkgs.add(pkg.name)

    # Check whether all the user requested blocks have been removed. If they
    # haven't, then it may indicate a user input (they've used the wrong name,
    # or format); but it might not be an error either, so just output a
    # warning to the user.
    not_handled = set(remove_pkgs) - handled_remove_pkgs
    if not_handled:
        msg = (
            "Some user specified RPMs to be removed have not had any "
            "impact. This may be expected, but may be due to a user "
            "error: {}".format(" ".join(sorted(not_handled)))
        )
        _log.warning(msg)
        print(f"WARNING: {msg}")


class DuplicatePackagesError(Exception):
    """
    Error for duplicate packages in the output GISO.

    """

    def __init__(
        self, duplicates: Dict[str, Sequence[_blocks.AnyBlock]]
    ) -> None:
        super().__init__(duplicates)
        self.duplicates = duplicates

    def __str__(self) -> str:
        lines = ["Duplicate blocks in output GISO packages:"]
        for name, blocks_ in sorted(self.duplicates.items()):
            versions = ", ".join(str(block.evra) for block in blocks_)
            lines.append(f"  {name} at versions {versions}")
        return "\n".join(lines)


def _check_duplicates(output_pkgs: _blocks.GroupedPackages) -> None:
    """
    Check that there are no duplicates in the GISO output packages.

    :param output_pkgs:
        The collection of packages in the output GISO.

    """
    duplicates: Dict[str, Sequence[_blocks.AnyBlock]] = dict()
    for name, block_versions in output_pkgs.blocks.items():
        if len(block_versions) > 1:
            duplicates[name] = list(block_versions.values())
    for name, tie_block_versions in output_pkgs.tie_blocks.items():
        if len(tie_block_versions) > 1:
            duplicates[name] = list(tie_block_versions.values())

    if duplicates:
        raise DuplicatePackagesError(duplicates)


def pick_installable_pkgs(
    iso_pkgs: _blocks.GroupedPackages,
    additional_pkgs: _blocks.GroupedPackages,
    add_pkg_patterns: Sequence[str],
    remove_pkgs: Sequence[str],
) -> _blocks.GroupedPackages:
    """
    Pick the packages to go into the installable groups of the GISO.

    :param iso_pkgs:
        The packages in the input iso grouped into logical blocks.

    :param additional_pkgs:
        The additional packages from the repositories grouped into logical
        blocks.

    :param add_pkg_patterns:
        List of patterns to specify to add packages. This can either be
        explicit .rpm filenames or package names. If a pattern matches a
        package in a block then the whole block is added.

    :param remove_pkgs:
        List of packages to remove. If a pattern matches a
        package in a block then the whole block is removed.

    :return:
        The packages grouped into logical blocks to include in the output GISO.

    """
    add_pkg_filenames, add_pkg_res = _split_add_pkg_patterns(add_pkg_patterns)

    output_pkgs = _blocks.GroupedPackages()

    _add_blocks(
        additional_pkgs.blocks,
        iso_pkgs.blocks,
        output_pkgs,
        add_pkg_filenames,
        add_pkg_res,
    )
    _add_blocks(
        additional_pkgs.tie_blocks,
        iso_pkgs.tie_blocks,
        output_pkgs,
        add_pkg_filenames,
        add_pkg_res,
    )
    _add_blocks(
        additional_pkgs.owner_pkgs,
        iso_pkgs.owner_pkgs,
        output_pkgs,
        add_pkg_filenames,
        add_pkg_res,
    )
    _add_blocks(
        additional_pkgs.partner_pkgs,
        iso_pkgs.partner_pkgs,
        output_pkgs,
        add_pkg_filenames,
        add_pkg_res,
    )
    _remove_blocks(output_pkgs, remove_pkgs)

    _check_duplicates(output_pkgs)

    return output_pkgs


class BaseAction(abc.ABC):
    """
    Base class to represent an action to perform to create the output GISO.

    """

    @abc.abstractmethod
    def run(self, output_dir: str) -> None:
        """
        Abstract method defined by all subclasses to run the action.

        :param output_dir:
            The path to the output GISO directory.

        """


@dataclasses.dataclass
class RemovePkgAction(BaseAction):
    """
    Output action to remove a package from the output directory.

    .. attribute:: pkg

        The path to the package to remove.

    """

    pkg: pathlib.Path
    iso_content: Dict[str, Any]
    group: str

    def run(self, output_dir: str) -> None:
        """
        Run the action to remove the package from the output directory.

        :param output_dir:
            The path to the output GISO directory.

        """
        _log.debug("Removing package %s from the iso", str(self.pkg))
        _file.remove_package(self.pkg.name, output_dir, self.iso_content)


@dataclasses.dataclass
class AddPkgAction(BaseAction):
    """
    Output action to add a package to the output directory.

    .. attribute:: pkg

        The path to the package to add.

    .. attribute:: group

        The group to which the package should be added

    """

    pkg: pathlib.Path
    group: _isoformat.PackageGroup

    def run(self, output_dir: str) -> None:
        """
        Run the action to add the package to the output directory.

        :param output_dir:
            The path to the output GISO directory.

        """
        _log.debug("Adding package %s to the iso", str(self.pkg))
        _file.add_rpm(str(self.pkg), output_dir, group=self.group)


def determine_output_actions(
    grouped_output_pkgs: _blocks.GroupedPackages,
    grouped_input_pkgs: _blocks.GroupedPackages,
    pkg_to_filepath: Mapping[_packages.Package, pathlib.Path],
    iso_content: Dict[str, Any],
) -> List[BaseAction]:
    """
    Determine the actions to perform to assemble packages for the output GISO.

    :param grouped_output_pkgs:
        The packages to be included in the output GISO grouped into logical
        blocks.

    :param grouped_input_pkgs:
        The packages in the input ISO grouped into logical blocks.

    :param pkg_to_filepath:
        Mapping of :class:`._packages.Package` object to the file path for that
        package.

    :param iso_content:
        Iso metadata, as a parsed json object returned from query content.
        This is slightly naff but we need to pass this in for when we call the
        _file.remove_package API.

    :return:
        A list of actions to assemble the packages in the output GISO
        directory.

    """
    actions: List[BaseAction] = []
    for group in _isoformat.PackageGroup:
        output_pkgs = grouped_output_pkgs.get_all_pkgs(group)
        input_pkgs = grouped_input_pkgs.get_all_pkgs(group)
        for pkg in input_pkgs - output_pkgs:
            actions.append(
                RemovePkgAction(
                    pkg_to_filepath[pkg], iso_content, group=group.group_name
                )
            )
        for pkg in output_pkgs - input_pkgs:
            actions.append(AddPkgAction(pkg_to_filepath[pkg], group=group))
    return actions
