# -----------------------------------------------------------------------------

""" Provides APIs for interacting with packages.

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
    "EVRA",
    "Version",
    "PackageDep",
    "Package",
    "UnspecifiedRPMAttrError",
    "get_packages_from_repodata",
    "get_packages_from_rpm_files",
)


import dataclasses
import hashlib
import logging
import os
import pathlib

from typing import (
    cast,
    Collection,
    Dict,
    FrozenSet,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from xml.etree.ElementTree import Element, ElementTree

import defusedxml.ElementTree as elemtree  # type: ignore

from . import _multiprocessing
from . import _runrpm
from .. import gisoutils


_log = logging.getLogger(__name__)


class UnspecifiedRPMAttrError(Exception):
    """Error if required RPM attribute is not found."""

    def __init__(self, attr: str, rpm_path: str, output: List[str]) -> None:
        """Initialise UnspecifiedRPMAttrError"""
        super().__init__(
            "The RPM query on {} did not return information for the '{}' "
            "attribute. Query output:\n  {}".format(
                rpm_path, attr, "\n  ".join(output)
            )
        )


class RepodataMissingMandatoryTagError(Exception):
    """Exception if repodata XML is missing a mandatory tag."""

    def __init__(self, tag: str) -> None:
        super().__init__(
            "Unable to find the mandatory tag '{}'; in RPM XML data.".format(
                tag
            )
        )


class RepodataMissingMandatoryAttrError(Exception):
    """Exception if repodata XML is missing a mandatory attribute."""

    def __init__(self, tag: str) -> None:
        super().__init__(
            "Unable to find the mandatory attribute '{}'; in RPM XML data.".format(
                tag
            )
        )


def _repodata_to_etree(repodata_str: str) -> ElementTree:
    # Convert the XML string into XML
    try:
        xml = elemtree.fromstring(repodata_str)
    except elemtree.ParseError:
        _log.error("Failed to parse XML")
        raise

    # Strip the namespace data for easier parsing.
    gisoutils.xml_strip_ns(xml)
    return cast(ElementTree, xml)


def _get_elem(data: Element, tag: str,) -> Optional[Element]:
    return data.find(tag)


def _get_item(data: Element, tag: str) -> str:
    elem = _get_elem(data, tag)
    if elem is None or elem.text is None:
        return ""
    else:
        return elem.text


def _get_attribute(data: Element, tag: str) -> str:
    if tag in data.attrib:
        return data.attrib[tag]
    else:
        return ""


@dataclasses.dataclass(frozen=True)
class Version:
    """
    Represents a package version containing methods to split into constituents.

    .. attribute:: version

        The package version string.

    """

    version: str

    def _split(self) -> Tuple[str, str]:
        """
        Split the version into XR and package version strings.

        :returns:
            A tuple of two elements:
              - the XR version string
              - the package version string
            For example a version of A.B.CvD.E.F would return "A.B.C" for the
            XR version and D.E.F for the package version.

        """
        # If version is of the form A.B.CvD.E.F, assume A.B.C is XR version and
        # D.E.F is package version. Otherwise, assume XR version is empty as
        # the package does not follow XR versioning scheme.
        toks = self.version.split("v")
        if len(toks) == 2:
            return (toks[0], toks[1])
        else:
            return ("", self.version)

    @property
    def xr_version(self) -> str:
        """
        Get the XR version out of the full RPM version string.

        """
        return self._split()[0]

    @property
    def pkg_version(self) -> str:
        """
        Get the package version out of the full RPM version string.

        """
        return self._split()[1]

    def __str__(self) -> str:
        """Return the version string"""
        return self.version


@dataclasses.dataclass(frozen=True)
class EVRA:
    """Combined "version" fields, useful e.g. as a mapping key."""

    epoch: str
    version: Version
    release: str
    arch: str

    def __str__(self) -> str:
        """Return the canonical form of these EVRA fields."""
        vra = f"{self.version.version}-{self.release}.{self.arch}"
        if self.epoch and self.epoch != "0":
            return f"{self.epoch}:{vra}"
        else:
            return vra


@dataclasses.dataclass(frozen=True)
class PackageDep:
    """
    Represents a dependency between packages.

    These are used to represent a requires, provides or conflicts tag. For
    example, a requires tag of "xr-foo = 7.5.1.17Iv1.0.0" indicates a
    requirement on "xr-foo" at version "7.5.1.17Iv1.0.0".

    Boolean dependencies store the full tag in the name field below. For
    example, a requires tag of "(xr-foo = 7.5.1.17Iv1.0.0 if xr-foo)" indicates
    a requirement on xr-foo if the package is present. We store this whole
    string in the name field which mimics rpm's behavior.

    .. attribute:: name

        The name of the package which is depended on. In the example above,
        this is "xr-foo".

    .. attribute:: flags

        The flags of the dependency. In the example above this is "=".

    .. attribute:: version

        The version of the dependency. In the example above this is
        "7.5.1.17Iv1.0.0".

    """

    name: str
    flags: Optional[str]
    version: Optional[str]

    def __str__(self) -> str:
        if self.flags is not None and self.version is not None:
            return f"{self.name} {self.flags} {self.version}"
        else:
            return self.name

    @classmethod
    def from_rpm_query_output(cls, query: str) -> "PackageDep":
        """
        Create an instance of this class from RPM query output.

        :param query:
            String containing the output from an RPM query for a package
            dependency.

        :return:
            The instance of this class.

        """
        toks = query.split()
        if len(toks) == 3:
            # For example:
            #   xr-foo = 1.2.3v1.0.0
            # where:
            #   - name is "xr-foo"
            #   - flags is "="
            #   - version is "1.2.3v1.0.0"
            return cls(name=toks[0], flags=toks[1], version=toks[2])
        elif len(toks) == 1:
            # For example:
            #   xr-foo
            # where:
            #   - name is "xr-foo"
            #   - flags and version are empty
            return cls(name=toks[0], flags=None, version=None)
        else:
            # This is likely to be a boolean dependency and if so then just
            # store the whole string as the name to match rpm's behavior.
            # For example:
            #   (xr-foo = 1.2.3v1.0.0 if xr-foo)
            # where we store the whole string as name, and flags and version
            # are empty.
            # If toks has 2 elements then we'd also fall into this statement. I
            # don't think this should ever happen but just store it in the
            # name.
            return cls(name=query, flags=None, version=None)

    @classmethod
    def from_repodata_xml(cls, repodata: Element) -> "PackageDep":
        """Create a PackageDep based of an XML Element."""
        name = _get_attribute(repodata, "name")
        if not name:
            raise RepodataMissingMandatoryAttrError("name")

        flags = _get_attribute(repodata, "flags")
        version = _get_attribute(repodata, "version")

        return cls(name=name, flags=flags, version=version)


@dataclasses.dataclass(frozen=True)
class Package:
    """
    Represents a single RPM where each attribute corresponds to the RPM tag.

    """

    name: str
    epoch: str
    version: Version
    release: str
    arch: str
    group: str
    provides: FrozenSet[PackageDep]
    requires: FrozenSet[PackageDep]
    conflicts: FrozenSet[PackageDep]

    @property
    def evra(self) -> EVRA:
        """Return a combined "version fields" object for this package."""
        return EVRA(self.epoch, self.version, self.release, self.arch)

    @property
    def evr(self) -> str:
        """Return the epoch, version, release string for this package."""
        epoch = ""
        if self.epoch and self.epoch != "0":
            epoch = f"{self.epoch}:"
        return f"{epoch}{self.version}-{self.release}"

    @property
    def filename(self) -> str:
        """Return the filename for this RPM."""
        # Epoch isn't included in filename. It has format: N-V-R.A
        return f"{self.name}-{self.version}-{self.release}.{self.arch}.rpm"

    @property
    def is_third_party(self) -> bool:
        """Indicates whether the package is a third party package."""
        return "cisco-iosxr" not in {p.name for p in self.provides}

    @property
    def is_owner_package(self) -> bool:
        """Indicates whether this is a package produced by the device owner"""
        return self.name.startswith("owner-")

    @property
    def is_partner_package(self) -> bool:
        """Indicates whether this is a package produced by a Cisco partner"""
        return self.name.startswith("partner-")

    def __str__(self) -> str:
        """Return the canonical name for this package."""
        # Possible output formats are:
        #   N-E:V-R.A
        #   N-V-R.A
        version_str = str(self.evra)
        return f"{self.name}-{version_str}"

    @staticmethod
    def _query_rpm(rpm_path: str) -> List[str]:
        """
        Query the given RPM for information to create the Package object.

        :param rpm_path:
            The path to the RPM.

        :return:
            A list of strings containing the output from the RPM query.

        """
        fmt = (
            "[name: %{NAME}\n][epoch: %{EPOCH}\n][version: %{VERSION}\n]"
            "[release: %{RELEASE}\n][arch: %{ARCH}\n]"
            "[provides: %{PROVIDENAME} %{PROVIDEFLAGS:depflags} %{PROVIDEVERSION}\n]"
            "[requires: %{REQUIRENAME} %{REQUIREFLAGS:depflags} %{REQUIREVERSION}\n]"
            "[conflicts: %{CONFLICTNAME} %{CONFLICTFLAGS:depflags} %{CONFLICTVERSION}\n]"
            "[group: %{GROUP}\n]"
        )
        output = _runrpm.query_format(pathlib.Path(rpm_path), fmt)
        return output.splitlines()

    @classmethod
    def from_rpm_file(cls, rpm_path: str) -> "Package":
        """
        Build a package object from the specified rpm.

        :param rpm_path:
            Path to RPM file

        :returns:
            Parsed package object

        """
        output = cls._query_rpm(rpm_path)
        epoch = ""
        name = None
        version = None
        release = None
        arch = None
        group = None
        provides: Set[PackageDep] = set()
        requires: Set[PackageDep] = set()
        conflicts: Set[PackageDep] = set()
        for line in output:
            line_toks = line.split(": ", maxsplit=1)
            if len(line_toks) != 2:
                continue
            field, value = line_toks
            if field == "name":
                name = value
            elif field == "epoch":
                epoch = value
            elif field == "version":
                version = value
            elif field == "release":
                release = value
            elif field == "arch":
                arch = value
            elif field == "provides":
                provides.add(PackageDep.from_rpm_query_output(value))
            elif field == "requires":
                requires.add(PackageDep.from_rpm_query_output(value))
            elif field == "conflicts":
                conflicts.add(PackageDep.from_rpm_query_output(value))
            elif field == "group":
                group = value

        mandatory_fields = {
            "name": name,
            "arch": arch,
            "version": version,
            "release": release,
            "group": group,
        }
        for key, attr in mandatory_fields.items():
            if attr is None:
                raise UnspecifiedRPMAttrError(key, rpm_path, output)

        # Keep mypy happy
        assert name is not None
        assert version is not None
        assert release is not None
        assert arch is not None
        assert group is not None

        return Package(
            name=name,
            epoch=epoch,
            version=Version(version),
            release=release,
            arch=arch,
            group=group,
            provides=frozenset(provides),
            requires=frozenset(requires),
            conflicts=frozenset(conflicts),
        )

    @classmethod
    def from_repodata_xml(cls, repodata: Element, group: str) -> "Package":
        """Create a Package based of an XML Element."""
        name = _get_item(repodata, "name")
        assert name, "Cannot determine name for package from XML"
        arch = _get_item(repodata, "arch")
        version_data = _get_elem(repodata, "version")

        if version_data:
            epoch = _get_attribute(version_data, "epoch")
            version = _get_attribute(version_data, "version")
            release = _get_attribute(version_data, "rel")
        else:
            epoch = ""
            version = ""
            release = ""

        format_data = _get_elem(repodata, "format")

        def _get_deps_from_format_data(dep_type: str) -> List[PackageDep]:
            """Get the dependency information from the format element."""
            if format_data:
                dep_data = _get_elem(format_data, dep_type)
            else:
                dep_data = None
            if dep_data:
                return [
                    PackageDep.from_repodata_xml(dep)
                    for dep in dep_data.iterfind("entry")
                ]
            else:
                return []

        provides = _get_deps_from_format_data("provides")
        requires = _get_deps_from_format_data("requires")
        conflicts = _get_deps_from_format_data("conflicts")

        return cls(
            name=name,
            epoch=epoch,
            version=Version(version),
            release=release,
            arch=arch,
            group=group,
            provides=frozenset(provides),
            requires=frozenset(requires),
            conflicts=frozenset(conflicts),
        )


def _rpm_file_to_rpm_file_and_package(filepath: str) -> Tuple[str, Package]:
    """
    Helper function for use with map to wrap Package.from_rpm_file and return
    both it's input argument and it's output.

    :param filepath:
        Path to an RPM file.

    :returns:
        A pair consisting of:
            - the input 'filepath'
            - a :class:`.Package` object representing 'filepath'
    """
    return filepath, Package.from_rpm_file(filepath)


def get_packages_from_rpm_files(
    filepaths: Collection[str],
) -> Dict[str, Package]:
    """
    Get a list of packages from a list of RPM file paths.

    :param filepaths:
        List of paths to RPM files to get the package data for.

    :return:
        Dictionary mapping the input paths to the :class:`.Package` objects
        representing them.

    """
    return dict(
        _multiprocessing.map_helper(
            _rpm_file_to_rpm_file_and_package, filepaths
        )
    )


def get_packages_from_repodata(
    repodata_str: str, group: str = ""
) -> List[Package]:
    """
    Get a list of packages from an XML based ElementTree.

    :param repodata:
        XML data to get the package data for.

    :param group:
        The group name associated with these packages.

    :return:
        List of :class:`.Package` objects representing these RPMs.

    """
    repodata = _repodata_to_etree(repodata_str)
    return [
        Package.from_repodata_xml(data, group)
        for data in repodata.iter()
        if _get_attribute(data, "type") == "rpm"
    ]


class DifferentPackageError(Exception):
    """
    Error representing RPM files of the same name which aren't identical.

    .. attribute:: pkg

        The package that has multiple non-identical copies on disk.

    .. attribute:: paths

        The paths where the package can be found.

    """

    def __init__(self, pkg: Package, paths: Sequence[pathlib.Path]) -> None:
        """
        Initialize the class.

        :param pkg:
            The package where multiple versions with different hashes have been
            found.

        :param paths:
            The paths found to the package.

        """
        super().__init__(pkg, paths)
        self.pkg = pkg
        self.paths = paths

    def __str__(self) -> str:
        """Format the error"""
        return "These RPMs for {} are not identical: {}".format(
            str(self.pkg), ", ".join([str(p) for p in self.paths])
        )


class PackageNotFoundError(Exception):
    """
    Error if a package cannot be found when mapping to file paths.

    .. attribute:: pkg

        The package which cannot be found on disk.

    """

    def __init__(self, pkg: Package) -> None:
        """
        Initialize the class.

        :param pkg:
            The package which cannot be found.

        """
        super().__init__(pkg)
        self.pkg = pkg

    def __str__(self) -> str:
        """Format error string."""
        return f"The package {str(self.pkg)} cannot be found"


PackageFileErrorTypes = Union[DifferentPackageError, PackageNotFoundError]


class PackageFilesError(Exception):
    """
    Error containing a collation of errors when mapping packages to file paths.

    .. attribute:: all_errors

        List of all errors found when gathering this mapping.

    .. attribute:: not_found_errors

        List of errors of type :class:`.PackageNotFoundError` to represent a
        package which cannot be found on disk.

    .. attribute:: different_rpm_errors

        List of errors of type :class:`.DifferentPackageError` to represent a
        package which has multiple versions on disk which are not identical.

    """

    def __init__(self, errors: List[PackageFileErrorTypes]) -> None:
        """
        Initialize the class.

        :param errors:
            The list of errors found while mapping packages to files on disk.

        """
        super().__init__(errors)
        self.all_errors = errors
        self.not_found_errors = [
            e for e in self.all_errors if isinstance(e, PackageNotFoundError)
        ]
        self.different_rpm_errors = [
            e for e in self.all_errors if isinstance(e, DifferentPackageError)
        ]

    def __str__(self) -> str:
        """Format the error."""
        lines = []
        if self.not_found_errors:
            lines.append("The following packages cannot be found:")
            for not_found_err in self.not_found_errors:
                lines.append(f"  {str(not_found_err.pkg)}")
        if self.different_rpm_errors:
            lines.append(
                "Packages have been found in multiple locations with "
                "different hashes:"
            )
            for different_rpm_err in self.different_rpm_errors:
                lines.append(str(different_rpm_err))
        return "\n".join(lines)


def _check_identical_pkgs(pkg: Package, paths: Sequence[pathlib.Path]) -> None:
    """
    Check all the RPMs are bit-for-bit identical.

    :param pkg:
        The package being checked.

    :param paths:
        Collection of paths to the package.

    :raises DifferentPackageError:
        If any of the packages differ.

    """
    hashes = set()
    for path in paths:
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
            _log.debug("Hash for %s is %s", str(path), digest)
            hashes.add(digest)

    if len(hashes) > 1:
        if pkg.is_third_party:
            # Third party packages are rebuilt for every SMU that provides
            # them, and do not maintain the same hash - so do not raise an
            # error in this case. However, we will still log it (as an error).
            _log.error(
                "Third party package error being ignored: %s",
                DifferentPackageError(pkg, paths),
            )
        else:
            raise DifferentPackageError(pkg, paths)


def _check_found_paths(
    pkg_to_paths: Mapping[Package, Sequence[pathlib.Path]]
) -> List[PackageFileErrorTypes]:
    """
    Check the paths found for each package.

    :param pkg_to_paths:
        Mapping of package to the paths where that package is found.

    :return:
        List of errors found for the given paths. The errors can be of the
        following types:
        - :class:`.DifferentPackageError` if there is more than one file path
          to a package and the files are not identical.
        - :class:`.PackageNotFoundError` if the package cannot be found
          anywhere.

    """
    errors: List[PackageFileErrorTypes] = []
    for pkg, paths in pkg_to_paths.items():
        if len(paths) > 1:
            try:
                _check_identical_pkgs(pkg, paths)
            except DifferentPackageError as e:
                errors.append(e)
        elif len(paths) == 0:
            errors.append(PackageNotFoundError(pkg))

    return errors


def _find_pkg(
    pkg: Package, dirs: Sequence[pathlib.Path]
) -> List[pathlib.Path]:
    """
    Find a package in the given directories.

    :param pkg:
        The package to find.

    :param dirs:
        The paths to the directories to look for the package in.

    :return:
        The set of paths where the package is found.

    """
    candidate_paths = (dirpath / pkg.filename for dirpath in dirs)
    found_paths = [path for path in candidate_paths if path.exists()]

    if found_paths:
        _log.debug(
            "Package %s found at file paths: %s",
            pkg.filename,
            ", ".join(sorted(str(p) for p in found_paths)),
        )
    else:
        _log.debug("Package %s not found at any locations", pkg.filename)

    return found_paths


def _get_all_dirs(dirs: Sequence[str]) -> Sequence[pathlib.Path]:
    """Get all the directories in the given list of directories."""
    all_dirs = []
    for dir_str in dirs:
        if pathlib.Path(dir_str) in all_dirs:
            continue
        for subdir, _, _ in os.walk(dir_str):
            subdir_path = pathlib.Path(subdir)
            if subdir_path not in all_dirs:
                all_dirs.append(subdir_path)
    return all_dirs


def packages_to_file_paths(
    pkgs: Iterable[Package], dirs: Sequence[str]
) -> Dict[Package, pathlib.Path]:
    """
    Get a mapping of :class:`.Package` objects to their path on disk.

    :param pkgs:
        Collection of packages to find file paths for.

    :param dirs:
        Sequence of paths to directories containing the RPMs. If a package is
        found in multiple directories, then it is checked that the RPMs are
        identical and if they are then the first match in the sequence of
        directories is used.

    :raises PackageFilesError:
        Raised if any of the packages cannot be found or aren't bit-for-bit
        identical.

    :return:
        A mapping of :class:`.Package` to the file path that package is found
        at.

    """
    all_dirs = _get_all_dirs(dirs)
    pkg_to_paths = dict()
    _log.debug(
        "Searching for packages in directories %s",
        ", ".join([str(d) for d in all_dirs]),
    )
    for pkg in pkgs:
        pkg_to_paths[pkg] = _find_pkg(pkg, all_dirs)

    errors = _check_found_paths(pkg_to_paths)

    if errors:
        raise PackageFilesError(errors)

    return {pkg: paths[0] for pkg, paths in pkg_to_paths.items()}
