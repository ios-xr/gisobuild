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

"""Provides APIs for interacting with groups of RPMs as blocks."""

__all__ = (
    "CantGroupPkgsByPidError",
    "Block",
    "GroupedPackages",
    "TieBlock",
    "get_xr_foundation_package",
    "get_xr_optional_packages",
    "get_xr_required_packages",
    "group_packages",
    "is_xr_installable_pkg",
    "is_xr_pkg",
)

import collections
import dataclasses
import itertools
import logging
import re
from typing import (
    Dict,
    FrozenSet,
    Iterable,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

from . import _isoformat, _packages

_log = logging.getLogger(__name__)


class CantGroupPkgsByPidError(Exception):
    """Error if failed to group packages by PID."""


class DuplicateEvraError(Exception):
    """
    Error if multiple matching packages have been specified for a given block.

    """

    def __init__(
        self,
        evra: _packages.EVRA,
        pkg1: _packages.Package,
        pkg2: _packages.Package,
    ) -> None:
        """Initialise a DuplicateEvraError."""
        super().__init__(evra, pkg1, pkg2)
        self.evra = evra
        self.pkg1 = pkg1
        self.pkg2 = pkg2

    def __str__(self) -> str:
        return (
            f"Multiple instances of RPM {self.evra} have been specified. "
            f"Check the contents of {self.pkg1} and {self.pkg2} to remove "
            "duplications."
        )


def is_xr_pkg(pkg: _packages.Package) -> bool:
    """
    Return a boolean indicating whether the given package is an XR package.

    XR packages have a provides tag for "cisco-iosxr".

    """
    return (
        _get_provides_by_name(pkg, "cisco-iosxr") is not None
        and _get_provides_by_name(pkg, "cisco-rebuilt") is None
    )


def is_xr_installable_pkg(pkg: _packages.Package) -> bool:
    """
    Return a boolean indicating whether the given package is an XR package
    that can be installed by the user.

    XR packages have a provides tag for "cisco-iosxr-user-installable".

    """
    return (
        _get_provides_by_name(pkg, "cisco-iosxr-user-installable") is not None
    )


@dataclasses.dataclass(frozen=True)
class Block:
    """
    Representation of a regular, partitioned block.

    .. attribute:: name

        Name of the block, e.g. `'xr-bgp'`

    .. attribute:: evra

        Epoch, version, release, architecture for every package in the block.

    .. attribute:: top_pkg

        Top-level, user-installable package.

    .. attribute:: instance_pkgs

        All instance packages for the block.

    .. attribute:: partition_pkgs

        All partition packages for the block. This may also contain per-pid
        third party packages, such as SDK packages.

    """

    name: str
    evra: _packages.EVRA
    top_pkg: _packages.Package
    instance_pkgs: Set[_packages.Package]
    partition_pkgs: Set[_packages.Package]

    @property
    def all_pkgs(self) -> List[_packages.Package]:
        """
        Return a list of all packages in the block

        """
        return (
            [self.top_pkg]
            + list(self.instance_pkgs)
            + list(self.partition_pkgs)
        )

    def _get_instance_pkg_on_pid(
        self, pid: str
    ) -> Optional[_packages.Package]:
        """Get the instance packages on the given PID."""
        # Instance packages have a requires tag for cisco-pid-<pid-name> to
        # indicate it belongs on <pid-name>.
        # If this is the xr-identifier package, then the instance package
        # provides the tag instead.
        for pkg in self.instance_pkgs:
            if _get_requires_by_name(
                pkg, f"{_isoformat.CISCO_PID_PREFIX}{pid}"
            ) is not None or _get_provides_by_name(
                pkg, f"{_isoformat.CISCO_PID_PREFIX}{pid}"
            ):
                return pkg
        return None

    def _get_partition_pkgs_for_instance(
        self, instance: _packages.Package
    ) -> Set[_packages.Package]:
        """Get the partition packages for the given instance package."""
        # Instance packages have a requires tag on the appropriate partition
        # packages.
        # - In the case of XR blocks, they will be of the format
        #   "<block-name>-<partition-hash>"
        # - In the case of per-PID Tie-blocks, they have no specific format.
        # So check all requires tags of the package to see if any of them
        # match a partition package.
        out = set()
        name_to_partition = {pkg.name: pkg for pkg in self.partition_pkgs}
        for req in instance.requires:
            if req.name in name_to_partition:
                out.add(name_to_partition[req.name])
        return out

    def get_pkgs_on_pid(self, pid: str) -> Set[_packages.Package]:
        """
        Get the set of packages on the given PID.

        :param pid:
            The PID to get the packages for.

        :return:
            The set of packages on the given PID.

        """
        # The top-level package goes everywhere so always include that.
        # Instance and partition packages are pid-dependent.
        pkgs = set([self.top_pkg])
        instance = self._get_instance_pkg_on_pid(pid)
        if instance is not None:
            pkgs.add(instance)
            pkgs |= self._get_partition_pkgs_for_instance(instance)
        return pkgs

    def filter_pkgs(
        self, pkgs_to_remove: Set[_packages.Package]
    ) -> "FilteredBlock":
        """
        Return a FilteredBlock containing the packages in this block, minus
        the given packages.

        :param pkgs_to_remove:
            Packages to remove.
        """
        return FilteredBlock(
            self.name,
            self.evra,
            self.top_pkg,
            self.instance_pkgs - pkgs_to_remove,
            self.partition_pkgs - pkgs_to_remove,
        )


class FilteredBlock(Block):
    """A Block whose packages have been filtered down to only support a subset
    of PIDs on this platform."""


@dataclasses.dataclass
class TieBlock:
    """
    Representation of a thirdparty tie block.

    .. attribute:: name

        Name of the block, e.g. `'xr-os-core'`

    .. attribute:: evra

        Epoch, version, release, architecture for the top-level package.

    .. attribute:: top_pkg

        Top-level, user-installable package.

    .. attribute:: tied_pkgs

        All thirdparty packages for the block.

    """

    name: str
    evra: _packages.EVRA
    top_pkg: _packages.Package
    tied_pkgs: Set[_packages.Package]

    @property
    def all_pkgs(self) -> List[_packages.Package]:
        """
        Return a list of all packages in the block

        """
        return [self.top_pkg] + list(self.tied_pkgs)

    def get_pkgs_on_pid(self, _: str) -> Set[_packages.Package]:
        """
        Get the set of packages on the given PID.

        :param pid:
            The PID to get the packages for.

        :return:
            The set of packages on the given PID.

        """
        # At the moment, all third party packages go to every PID.
        return set(self.all_pkgs)


AnyBlock = Union[Block, TieBlock]


class NoBlockForPkgError(Exception):
    """
    Error if no block can be found for a constituent package.

    """

    def __init__(self, block_name: str, pkg: _packages.Package) -> None:
        """
        Initialize the class.

        :param block_name:
            The name of the block for the package.

        :param pkg:
            The package for which a block at the correct version cannot be
            found.

        """
        super().__init__(block_name, pkg)
        self.block_name = block_name
        self.pkg = pkg

    def __str__(self) -> str:
        return (
            f"Cannot find a top-level block package for {str(self.pkg)} in "
            f"block {self.block_name}"
        )


@dataclasses.dataclass
class GroupedPackages:
    """
    A set of packages grouped into logical blocks.

    Each of the fields below map the block/package name to a mapping of version
    to the :class:`.Package` object of the given RPM.

    .. attribute:: blocks

        The standard XR blocks in this set of packages. The foundation and
        packages are considered blocks without instance or partition RPMs.

    .. attribute:: tie_blocks

        The third-party tie blocks in this set of packages including the tied
        OS RPMs.

    .. attribute: owner_pkgs

        Owner packages

    .. attribute: partner_pkgs

        Partner packages

    """

    blocks: Dict[str, Dict[_packages.EVRA, Block]] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(dict)
    )
    tie_blocks: Dict[str, Dict[_packages.EVRA, TieBlock]] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(dict)
    )
    owner_pkgs: Dict[str, Dict[_packages.EVRA, Block]] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(dict)
    )
    partner_pkgs: Dict[str, Dict[_packages.EVRA, Block]] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(dict)
    )

    def get_tie_ui_pkgs(self) -> Iterator[Tuple[str, _packages.Package]]:
        """
        Yield all user-installable tie packages in this group.

        Yields `(block name, user-installable tie package)` pairs.

        """
        for block_name, versioned_tie_blocks in self.tie_blocks.items():
            for tie_block in versioned_tie_blocks.values():
                yield block_name, tie_block.top_pkg

    @property
    def all_blocks(self) -> Iterator[AnyBlock]:
        """Iterate over all the blocks."""
        yield from [
            block
            for block_versions in self.blocks.values()
            for block in block_versions.values()
        ]
        yield from [
            tie_block
            for block_versions in self.tie_blocks.values()
            for tie_block in block_versions.values()
        ]

    @property
    def all_owner_pkgs(self) -> Iterator[_packages.Package]:
        """Iterate over all owner packages"""
        yield from [
            pkg
            for block_versions in self.owner_pkgs.values()
            for block in block_versions.values()
            for pkg in block.all_pkgs
        ]

    @property
    def all_partner_pkgs(self) -> Iterator[_packages.Package]:
        """Iterate over all partner packages"""
        yield from [
            pkg
            for block_versions in self.partner_pkgs.values()
            for block in block_versions.values()
            for pkg in block.all_pkgs
        ]

    @property
    def supported_pids(self) -> Set[str]:
        """Iterate over all supported PIDs."""
        return {
            pid
            for pid, _, _ in get_pid_identifier_packages(
                self.get_all_pkgs(_isoformat.PackageGroup.INSTALLABLE_XR_PKGS)
            )
        }

    def get_all_pkgs(
        self, group: _isoformat.PackageGroup
    ) -> Set[_packages.Package]:
        """Get the set of all packages in this group."""
        all_pkgs: Set[_packages.Package] = set()
        if group == _isoformat.PackageGroup.INSTALLABLE_XR_PKGS:
            for block in self.all_blocks:
                all_pkgs |= set(block.all_pkgs)
        elif group == _isoformat.PackageGroup.INSTALLABLE_OWNER_PKGS:
            all_pkgs = set(self.all_owner_pkgs)
        elif group == _isoformat.PackageGroup.INSTALLABLE_PARTNER_PKGS:
            all_pkgs = set(self.all_partner_pkgs)
        return all_pkgs

    def get_all_pkgs_all_groups(self) -> Set[_packages.Package]:
        """Get the set of all packages in all groups."""
        return {
            pkg
            for group in _isoformat.PackageGroup
            for pkg in self.get_all_pkgs(group)
        }

    def get_pkgs_per_pid(self) -> Dict[str, Set[_packages.Package]]:
        """Get a mapping of PID to the packages on that PID."""
        pid_to_pkgs = dict()
        chosen_rp = None
        for pid, pkg, card_type in get_pid_identifier_packages(
            self.get_all_pkgs(_isoformat.PackageGroup.INSTALLABLE_XR_PKGS)
        ):
            pid_to_pkgs[pid] = set([pkg])

            for block in self.all_blocks:
                pid_to_pkgs[pid] |= block.get_pkgs_on_pid(pid)

            if card_type in _isoformat.RP_CARD_TYPES:
                if chosen_rp is None or pid < chosen_rp:
                    chosen_rp = pid

        # Add a pseudo-PID for checking owner + partner packages, if needed
        owner_pkgs = set(self.all_owner_pkgs)
        partner_pkgs = set(self.all_partner_pkgs)
        if owner_pkgs or partner_pkgs:
            if chosen_rp is None:
                raise CantGroupPkgsByPidError(
                    "Unable to group the packages by PID, no RP card type was found"
                )
            pid_to_pkgs["OwnerAndPartnerPackages"] = (
                pid_to_pkgs[chosen_rp] | owner_pkgs | partner_pkgs
            )

        if not pid_to_pkgs:
            raise CantGroupPkgsByPidError(
                "Unable to group the packages by PID, no PID identifier "
                "packages were found."
            )

        # Error if there are any packages that haven't been grouped onto a pid.
        # This should never happen.
        all_grouped_pkgs = set()
        for pkgs in pid_to_pkgs.values():
            all_grouped_pkgs |= pkgs
        all_pkgs = (
            self.get_all_pkgs(_isoformat.PackageGroup.INSTALLABLE_XR_PKGS)
            | set(self.all_owner_pkgs)
            | set(self.all_partner_pkgs)
        )
        ungrouped_pkgs = all_pkgs - all_grouped_pkgs
        if ungrouped_pkgs:
            raise NotImplementedError(
                "Unable to group the following packages by pid: {}".format(
                    ", ".join(
                        [str(pkg) for pkg in sorted(ungrouped_pkgs, key=str)]
                    )
                )
            )
        return pid_to_pkgs

    def add_block(self, block: AnyBlock) -> None:
        """Add a new block with the given EVRA."""
        # Repeat ourselves to placate the type checker.
        evra = block.evra
        if isinstance(block, Block):
            if block.top_pkg.is_owner_package:
                _log.debug(
                    "Adding block of owner package %s", str(block.top_pkg)
                )
                blocks = self.owner_pkgs[block.name]

            elif block.top_pkg.is_partner_package:
                _log.debug(
                    "Adding block of partner package %s", str(block.top_pkg)
                )
                blocks = self.partner_pkgs[block.name]

            else:
                _log.debug(
                    "Adding block of top package %s", str(block.top_pkg)
                )
                blocks = self.blocks[block.name]
            if evra in blocks:
                raise DuplicateEvraError(
                    evra, block.top_pkg, blocks[evra].top_pkg
                )
            assert evra not in blocks
            blocks[evra] = block
        elif isinstance(block, TieBlock):
            _log.debug(
                "Adding tie block of top package %s", str(block.top_pkg)
            )
            tie_blocks = self.tie_blocks[block.name]
            assert isinstance(block, TieBlock)
            if evra in tie_blocks:
                raise DuplicateEvraError(
                    evra, block.top_pkg, tie_blocks[evra].top_pkg
                )
            tie_blocks[evra] = block
        else:
            raise NotImplementedError

    def remove_block(self, block: AnyBlock) -> None:
        """Remove a block with the given EVRA."""
        if isinstance(block, Block):
            del self.blocks[block.name][block.evra]
            if not self.blocks[block.name]:
                del self.blocks[block.name]
        elif isinstance(block, TieBlock):
            del self.tie_blocks[block.name][block.evra]
            if not self.tie_blocks[block.name]:
                del self.tie_blocks[block.name]
        else:
            raise NotImplementedError

    def remove_owner_pkg(self, pkg: _packages.Package) -> None:
        """Remove the given owner package"""
        del self.owner_pkgs[pkg.name][pkg.evra]
        if not self.owner_pkgs[pkg.name]:
            del self.owner_pkgs[pkg.name]

    def remove_partner_pkg(self, pkg: _packages.Package) -> None:
        """Remove the given partner package"""
        del self.partner_pkgs[pkg.name][pkg.evra]
        if not self.partner_pkgs[pkg.name]:
            del self.partner_pkgs[pkg.name]

    def _check_pkg_can_be_added(
        self,
        blocks: Union[
            Dict[str, Dict[_packages.EVRA, Block]],
            Dict[str, Dict[_packages.EVRA, TieBlock]],
        ],
        block_name: str,
        pkg: _packages.Package,
    ) -> None:
        """
        Check if there is a block for the given package at the correct version.

        :raises NoBlockForPkgError:
            If there isn't a block at the correct version to add this package
            to.

        """
        if block_name not in blocks or pkg.evra not in blocks[block_name]:
            raise NoBlockForPkgError(block_name, pkg)

    def add_instance_pkg(
        self, block_name: str, pkg: _packages.Package
    ) -> None:
        """Add an instance package to the given block."""
        _log.debug(
            "Adding instance package %s to block %s", str(pkg), block_name
        )
        self._check_pkg_can_be_added(self.blocks, block_name, pkg)
        self.blocks[block_name][pkg.evra].instance_pkgs.add(pkg)

    def add_partition_pkg(
        self, block_name: str, pkg: _packages.Package
    ) -> None:
        """Add an partition package to the given block."""
        _log.debug(
            "Adding partition package %s to block %s", str(pkg), block_name
        )
        if pkg.evra in self.blocks[block_name]:
            self.blocks[block_name][pkg.evra].partition_pkgs.add(pkg)
        else:
            # Check if this is a per-pid constituent third-party RPM. To
            # determine this, we need to find the top-level package that this
            # rebuilt TP RPM is associated with.
            # If this package is associated with the block, there must be a
            # dependency on the top-level package of the block.
            top_level_reqs = [
                req for req in pkg.requires if req.name == block_name
            ]
            if not top_level_reqs:
                raise NoBlockForPkgError(block_name, pkg)
            top_level_req = top_level_reqs[0]

            # Now match the package to the correct version of the block.
            matched = False
            for block in self.blocks[block_name].values():
                if top_level_req.version == block.evra.version.version:
                    block.partition_pkgs.add(pkg)
                    matched = True
                    break

            if not matched:
                raise NoBlockForPkgError(block_name, pkg)

    def add_tied_pkg(
        self,
        block_name: str,
        tie_pkg: _packages.Package,
        tied_pkg: _packages.Package,
    ) -> None:
        """Add a tied package to the given block."""
        _log.debug(
            "Adding tied package %s to tie block %s", str(tied_pkg), block_name
        )
        self._check_pkg_can_be_added(self.tie_blocks, block_name, tie_pkg)
        self.tie_blocks[block_name][tie_pkg.evra].tied_pkgs.add(tied_pkg)

    def add_owner_pkg(self, pkg: _packages.Package) -> None:
        """Add owner package"""
        _log.debug("Adding owner package %s", str(pkg))
        self.owner_pkgs[pkg.name][pkg.evra] = Block(
            pkg.name, pkg.evra, pkg, set(), set()
        )

    def add_partner_pkg(self, pkg: _packages.Package) -> None:
        """Add partner package"""
        _log.debug("Adding partner package %s", str(pkg))
        self.partner_pkgs[pkg.name][pkg.evra] = Block(
            pkg.name, pkg.evra, pkg, set(), set()
        )

    def filter_pkgs_to_supported_pids(
        self, pids_to_support: List[str]
    ) -> None:
        """Remove all packages that are not associated with the given set of
        PIDs to support."""
        assert len(pids_to_support) > 0

        pkgs_to_keep = set()
        for block in self.all_blocks:
            for pid in pids_to_support:
                pkgs_to_keep |= block.get_pkgs_on_pid(pid)
        pkgs_to_remove = self.get_all_pkgs_all_groups() - pkgs_to_keep

        _log.debug(
            "Packages marked for removal: %s",
            pkgs_to_remove,
        )

        def _remove_pkgs_from_group(
            collection: Dict[str, Dict[_packages.EVRA, Block]]
        ) -> None:
            for block_name, block_versions in collection.items():
                for block_evra, block in block_versions.items():
                    # Block.get_pkgs_on_pid always returns the top pkg, so as
                    # long as the ISO supports >0 PIDs, a block will never be
                    # completely empty.
                    assert len(set(block.all_pkgs) - pkgs_to_remove) > 0

                    # Remove some pkgs from the block only if necessary
                    if any((pkg in pkgs_to_remove) for pkg in block.all_pkgs):
                        _log.debug(
                            "Filtering block %s",
                            str(block.name),
                        )
                        block_versions[block_evra] = block.filter_pkgs(
                            pkgs_to_remove
                        )

            # Clear any empty block_version lists
            for block_name in list(collection.keys()):
                if not collection[block_name]:
                    del collection[block_name]

        _remove_pkgs_from_group(self.blocks)
        # At the moment, all tie block, owner and partner packages go to all
        # PIDs, so they can't be filtered. If this ever changes, the above
        # function can be called on those fields to enable filtering.


def _get_dep_by_name(
    deps: FrozenSet[_packages.PackageDep], name: str
) -> Optional[_packages.PackageDep]:
    """
    Return the dependency with the given name from the given set.

    Returns `None` if there is no dependency by that name.

    """
    for dep in deps:
        # Allow for boolean dependencies, e.g.
        #   (cisco-pid-88-LC0-36FH or cisco-pid-88-LC0-36FH-M)
        if dep.name == name or re.search(r"[( ]{}[) ]".format(name), dep.name):
            return dep
    return None


def _get_provides_by_name(
    pkg: _packages.Package, name: str
) -> Optional[_packages.PackageDep]:
    """
    Return the provides dependency with the given name for the given package.

    Returns `None` if there is no provides by that name.

    """
    return _get_dep_by_name(pkg.provides, name)


def _get_requires_by_name(
    pkg: _packages.Package, name: str
) -> Optional[_packages.PackageDep]:
    """
    Return the requires dependency with the given name for the given package.

    Returns `None` if there is no requires by that name.

    """
    return _get_dep_by_name(pkg.requires, name)


def _get_deps_by_suffix(
    deps: FrozenSet[_packages.PackageDep], suffix: str
) -> Iterator[_packages.PackageDep]:
    """Yield dependencies with the given suffix."""
    for dep in deps:
        if dep.name.endswith(suffix):
            yield dep


def _get_provides_by_suffix(
    pkg: _packages.Package, suffix: str
) -> Iterator[_packages.PackageDep]:
    """
    Yield provides dependencies with the given suffix for the given package.
    """
    yield from _get_deps_by_suffix(pkg.provides, suffix)


def _get_deps_by_prefix(
    deps: FrozenSet[_packages.PackageDep], prefix: str
) -> Iterator[_packages.PackageDep]:
    """Yield dependencies with the given prefix."""
    for dep in deps:
        if dep.name.startswith(prefix):
            yield dep


def _get_requires_by_prefix(
    pkg: _packages.Package, prefix: str
) -> Iterator[_packages.PackageDep]:
    """
    Yield requires dependencies with the given prefix for the given package.
    """
    yield from _get_deps_by_prefix(pkg.requires, prefix)


def _get_provides_by_prefix(
    pkg: _packages.Package, prefix: str
) -> Iterator[_packages.PackageDep]:
    """
    Yield provides dependencies with the given prefix for the given package.

    """
    yield from _get_deps_by_prefix(pkg.provides, prefix)


def get_pid_identifier_packages(
    pkgs: Iterable[_packages.Package],
) -> Iterator[Tuple[str, _packages.Package, str]]:
    """
    Yield the subset of packages that are PID identifiers.

    Yields `(pid name, package, pid type)` tuples

    """
    for pkg in pkgs:
        pid_deps = set(
            _get_provides_by_prefix(pkg, _isoformat.CISCO_PID_PREFIX)
        )

        if not pid_deps:
            # This package is not a PID identifier so move on
            continue

        if len(pid_deps) == 1:
            provider = pid_deps.pop()
            card_types = {
                provides.name[len(_isoformat.CISCO_CARD_TYPE_PREFIX) :]
                for provides in _get_provides_by_prefix(
                    pkg, _isoformat.CISCO_CARD_TYPE_PREFIX
                )
            }
            if len(card_types) != 1:
                raise NotImplementedError(
                    f"Package {pkg} appears to have multiple card types: {card_types}"
                )

            # Get the package's card type from the set.
            #
            # Pylint worries that this might raise StopIteration, but that
            # can't happen because we've already checked the set has size 1.
            card_type = next(  # pylint: disable=stop-iteration-return
                iter(card_types)
            )
            yield provider.name[
                len(_isoformat.CISCO_PID_PREFIX) :
            ], pkg, card_type
        else:
            raise NotImplementedError(
                f"Package {pkg} appears to be a PID identifier package "
                f"for more than one PID via these providers: {pid_deps}"
            )


def _get_ui_packages(
    pkgs: Iterable[_packages.Package],
) -> Iterator[_packages.Package]:
    """
    Yield the subset of the given packages that are user-installable.
    """
    for pkg in pkgs:
        if _get_provides_by_name(pkg, "cisco-iosxr-user-installable"):
            yield pkg


def _get_owner_packages(
    pkgs: Iterable[_packages.Package],
) -> Iterator[_packages.Package]:
    """
    Yield the subset of the given packages that are owner packages
    """
    for pkg in pkgs:
        if pkg.is_owner_package:
            yield pkg


def _get_partner_packages(
    pkgs: Iterable[_packages.Package],
) -> Iterator[_packages.Package]:
    """
    Yield the subset of the given packages that are partner packages
    """
    for pkg in pkgs:
        if pkg.is_partner_package:
            yield pkg


def _get_instance_packages(
    candidate_block_names: Set[str],
    pkgs: Iterable[_packages.Package],
) -> Iterator[Tuple[str, _packages.Package]]:
    """
    Yield the subset of the given packages that are block instance packages.

    Yields `(block name, package)` pairs, where the name identifies which block
    the package belongs to.

    :param candidate_block_names:
        Only instance packages belonging to a block named in this set are
        returned.
    :param pkgs:
        Packages to consider.

    """
    for pkg in pkgs:
        instance_deps = set()
        for possible_instance_dep in _get_provides_by_suffix(pkg, "-PID"):
            block_name, suffix = possible_instance_dep.name.rsplit(
                "-", maxsplit=1
            )
            assert suffix == "PID"
            if block_name in candidate_block_names:
                instance_deps.add((block_name, possible_instance_dep))

        if len(instance_deps) == 1:
            block_name = list(instance_deps)[0][0]
            yield block_name, pkg
        elif len(instance_deps) > 1:
            raise NotImplementedError(
                f"Package {pkg} appears to be an instance package "
                f"for multiple blocks via these providers: {instance_deps}"
            )


def _get_partition_packages(
    candidate_block_names: Set[str],
    pkgs: Iterable[_packages.Package],
) -> Iterator[Tuple[str, _packages.Package]]:
    """
    Yield the subset of the given packages that are block partition packages.

    Yields `(block name, package)` pairs, where the name identifies which block
    the package belongs to.

    :param candidate_block_names:
        Only partition packages belonging to a block named in this set are
        returned.
    :param pkgs:
        Packages to consider. This function operates correctly *only if* there
        are no top-level, user-installable block packages passed to this
        parameter.

    """
    for pkg in pkgs:
        partition_deps = set()
        for possible_partition_dep in _get_requires_by_prefix(pkg, "xr-"):
            block_name = possible_partition_dep.name
            if block_name in candidate_block_names:
                partition_deps.add((block_name, possible_partition_dep))

        if len(partition_deps) == 1:
            block_name = list(partition_deps)[0][0]
            yield block_name, pkg
        elif len(partition_deps) > 1:
            raise NotImplementedError(
                f"Package {pkg} appears to be a partition package "
                f"for multiple blocks via these requirements: {partition_deps}"
            )


def _get_tied_packages(
    tie_pkg: _packages.Package,
    pkgs: Iterable[_packages.Package],
) -> Iterator[_packages.Package]:
    """
    Yield the subset of the given packages that are thirdparty tied packages.

    :param tie_pkg:
        Only packages tied to this user-installable tie package are returned.
    :param pkgs:
        Packages to consider.

    """
    requirements = {dep.name: dep.version for dep in tie_pkg.requires}
    for pkg in pkgs:
        if str(requirements.get(pkg.name, None)) == pkg.evr:
            yield pkg


def _get_block_name(ui_pkg: _packages.Package) -> Optional[str]:
    """
    Given a user-installable package, return its XR block name (including xr-).

    Returns `None` if this RPM doesn't correspond to a block.

    """
    if _get_provides_by_name(ui_pkg, f"{ui_pkg.name}-BLOCK") is not None:
        return ui_pkg.name
    return None


def _get_block_from_ui_pkg(pkg: _packages.Package) -> AnyBlock:
    """
    Return a block object (of appropriate type) for a top-level package.
    """
    block_name = _get_block_name(pkg)
    if block_name is not None:
        if _get_requires_by_name(pkg, f"{block_name}-PID") is not None:
            # Regular block.
            return Block(
                name=block_name,
                evra=pkg.evra,
                top_pkg=pkg,
                instance_pkgs=set(),
                partition_pkgs=set(),
            )

        else:
            # Thirdparty tie block.
            return TieBlock(
                name=block_name, evra=pkg.evra, top_pkg=pkg, tied_pkgs=set()
            )

    elif (
        pkg.name == "xr-mandatory"
        or _get_provides_by_name(pkg, _isoformat.XR_FOUNDATION) is not None
    ):
        # Treat mandatory and foundation as regular blocks.
        #
        # N.B. in both cases use the top-level package name as the block
        # name (e.g. 'xr-8000-foundation').
        return Block(
            name=pkg.name,
            evra=pkg.evra,
            top_pkg=pkg,
            instance_pkgs=set(),
            partition_pkgs=set(),
        )

    else:
        raise NotImplementedError(
            "Don't know how to classify the user-installable package f{pkg!r}"
        )


class UngroupedXRPackagesError(Exception):
    """
    Error for any XR packages that cannot be grouped into blocks.

    """

    def __init__(self, pkgs: Set[_packages.Package]) -> None:
        """
        Initialize the class.

        :param pkgs:
            The packages which haven't been grouped.

        """
        super().__init__(pkgs)
        self.pkgs = pkgs

    def __str__(self) -> str:
        lines = ["Unable to group the following XR packages into blocks:"]
        lines.extend(sorted(f"  {str(pkg)}" for pkg in self.pkgs))
        return "\n".join(lines)


def group_packages(pkgs: Iterable[_packages.Package]) -> GroupedPackages:
    """
    Group packages into logical blocks.

    :param pkgs:
        The RPM packages to group.

    :return:
        A :class:`.GroupedPackages` object containing the RPMs grouped into
        logical blocks.

    """
    groups = GroupedPackages()

    # Find and process top-level, user-installable packages.
    all_pkgs = set(pkgs)
    ui_pkgs = set(_get_ui_packages(all_pkgs))
    remaining_pkgs = all_pkgs - ui_pkgs
    for pkg in ui_pkgs:
        groups.add_block(_get_block_from_ui_pkg(pkg))

    # Find and process block instance packages.
    all_block_names = set(itertools.chain(groups.blocks, groups.tie_blocks))
    instance_pkgs = list(
        _get_instance_packages(all_block_names, remaining_pkgs)
    )
    for block_name, pkg in instance_pkgs:
        try:
            groups.add_instance_pkg(block_name, pkg)
        except NoBlockForPkgError as e:
            # Doesn't match any version of the block; so don't remove from
            # remaining packages
            _log.debug(
                "No block found for instance package: %s",
                str(e),
            )
        else:
            remaining_pkgs.remove(pkg)

    # Find and process block partition packages, and per-pid third-party
    # packages.
    partition_pkgs = list(
        _get_partition_packages(all_block_names, remaining_pkgs)
    )
    for block_name, pkg in partition_pkgs:
        try:
            groups.add_partition_pkg(block_name, pkg)
        except NoBlockForPkgError as e:
            # Doesn't match any version of the block; so don't remove from
            # remaining packages
            _log.debug(
                "No block found for partition package: %s",
                str(e),
            )
        else:
            remaining_pkgs.remove(pkg)

    # Find and process thirdparty tied packages.
    #
    # A package might be tied to multiple tie blocks (e.g. consider multiple OS
    # bugfixes for a single release). Thus keep track of all packages consumed
    # here and substract from remaining only after processing all tie blocks.
    all_tied_pkgs = set()
    for block_name, tie_pkg in groups.get_tie_ui_pkgs():
        tied_pkgs = set(_get_tied_packages(tie_pkg, remaining_pkgs))
        for pkg in tied_pkgs:
            assert block_name in groups.tie_blocks
            assert tie_pkg.evra in groups.tie_blocks[block_name]
            groups.add_tied_pkg(block_name, tie_pkg, pkg)
            all_tied_pkgs.add(pkg)
    remaining_pkgs = remaining_pkgs - all_tied_pkgs

    # Find and process owner packages.
    owner_pkgs = set(_get_owner_packages(remaining_pkgs))
    remaining_pkgs = remaining_pkgs - owner_pkgs
    for pkg in owner_pkgs:
        groups.add_owner_pkg(pkg)

    # Find and process partner packages.
    partner_pkgs = set(_get_partner_packages(remaining_pkgs))
    remaining_pkgs = remaining_pkgs - partner_pkgs
    for pkg in partner_pkgs:
        groups.add_partner_pkg(pkg)

    # Anything left over, we don't know how to deal with.
    if remaining_pkgs:
        remaining_xr_pkgs = {pkg for pkg in remaining_pkgs if is_xr_pkg(pkg)}
        remaining_non_xr_pkgs = remaining_pkgs - remaining_xr_pkgs

        if remaining_non_xr_pkgs:
            _log.warning(
                "Ignoring the following non-XR packages left over after "
                "grouping:"
            )
            for pkg in remaining_non_xr_pkgs:
                _log.warning("    %s", pkg)

        if remaining_xr_pkgs:
            raise UngroupedXRPackagesError(remaining_xr_pkgs)

    return groups


def get_xr_foundation_package(
    pkgs: Iterable[_packages.Package],
) -> Optional[_packages.Package]:
    """Returns the foundation package (if found)."""
    for pkg in pkgs:
        if pkg.name.startswith(_isoformat.XR_FOUNDATION + "-"):
            return pkg

    return None


def get_xr_required_packages(
    foundation_pkg: Optional[_packages.Package],
    pkgs: Iterable[_packages.Package],
) -> List[_packages.Package]:
    """Returns all packages required by the specified foundation package."""
    if not foundation_pkg:
        _log.info("No foundation package, no known required packages.")
        return []

    foundation_deps = [dep.name for dep in foundation_pkg.requires]

    tail_str = "-BLOCK"
    foundation_deps = [
        dep[: -len(tail_str)] if dep.endswith(tail_str) else dep
        for dep in foundation_deps
    ]

    return [pkg for pkg in pkgs if pkg.name in foundation_deps] + [
        foundation_pkg
    ]


def get_xr_optional_packages(
    foundation_pkg: Optional[_packages.Package],
    pkgs: Iterable[_packages.Package],
    *,
    required_pkgs: Optional[Iterable[_packages.Package]] = None,
) -> List[_packages.Package]:
    """
    Return all optional RPMs (for XR).

    If required_pkgs is not set, then it is calculated.
    """
    if required_pkgs is None:
        required_pkgs = get_xr_required_packages(foundation_pkg, pkgs)

    _log.info("Required packages: %s", required_pkgs)

    optional_packages = [
        pkg
        for pkg in pkgs
        if pkg not in required_pkgs and is_xr_installable_pkg(pkg)
    ]
    _log.info("Optional packages: %s", required_pkgs)

    return optional_packages
