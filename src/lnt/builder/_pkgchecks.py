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

"""Module running various checks on packages including dependency checking."""

__all__ = ("CheckFailuresError", "run")


import contextlib
import enum
import functools
import logging
import pathlib
import tempfile
from typing import Iterator, List, Mapping, Optional, Sequence, Set, Union

from . import _blocks, _isoformat, _multiprocessing, _packages, _runrpm

_logger = logging.getLogger(__name__)


class KeyType(enum.Enum):
    """Types of key with which RPMs may be signed"""

    DUMMY = enum.auto()
    DEV = enum.auto()
    REL = enum.auto()


# Hardcoded keys for RPM signature checking
_GPG_DEV = """
-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: GnuPG v2.0.22 (GNU/Linux)

mQENBFzCrMkBCADqjBV/61Pobd/kegvq6Ot/YUHBkZSPYMmb//sqCzmU0/hjTsJ1
Ik7FpC6631eqirlM7REAv7K/8JP7BdYw0atY25QsVzy8EMLZENIt1PPwqvv5LhJF
MR2yaoi9F9T5DS82PsCvGt/KiCkkhupV6Z7t5Ef5mwoJYuiwusoGaOfumX05CYf4
Qz2g4GBaFTB/RKv6PhQzEQlYuZFAu0iJ8DE+6tLHUSN6OhViOqsviCvlC8+OYmj9
knhmKC6+wj/z2p8lx9G8ELuTID6Dn18nbo+/JhA+xWgKR026r7Qw9zJNATS06dji
/h/NnvmffuSqEP99pHJdR4QTMyTLhBXYsm4tABEBAAG0MWNpc2NvIChJT1MtWFIt
U1ctUlBNLmRldikgPHRhYy1zdXBwb3J0QGNpc2NvLmNvbT6JATkEEwECACMFAlzC
rMkCGwMHCwkIBwMCAQYVCAIJCgsEFgIDAQIeAQIXgAAKCRB0cngRXAaXa17UB/9T
wXrSm/GY+Ek0SDb+wcWU7CTxcIf3IenVYquZJ5Qzlf+pvFIlQslLOtRJJe1BqLXw
f+3dSI+WI98tbE53rZvu/qu3duzgEShweI3mFpbqmYBZ6Jrc7TaMc+GhTJFLiAGe
bJorb9R6iROs5Ma76FhbVM+g6FTNgK6Xhonte2+LvJpbJnLP9I5DNixJjpYfdtn7
52n3B/VazOrsrG5j764cL1FDiQrBaPra/HLpHXRztQzxFFEd7UMZfGmXWyEftaqK
kfWqeHxDv/H8N9TskZIYpDo04Wusxjfd2UDfpUHPUVBCMIrKoyJf0Nu2OtBVht2H
7HSrjKpS0I64PS7BVV2TuQENBFzCrMkBCADDneuFjQ9rttFB4/hR7WOWhTCuyJlU
QSoxq4r0UhKfBqoAq/3sHymvTncwsMPv7y5SF8DhhwVqMIEYN/zLFIax41FrjN3D
SNa+UT1AMhpWeQHgQVtNBfwDohn34ZcznpiwWupmnVWXmCPR5WUd4AScONPm3zbF
WMmHo88LI2+LgFCZTGoZPR6RGP6mrBkEnLvwnjwE64wFksmNHl55FcZOG7IGYE7F
ThrV0Pn2EFBPNzpisBfHtrGzqsVcjkTnoH2vrfZUp2CIeRP1SX/vXxczpXQa0ugW
JTzrQTs+sguk+In0RHAeTgasR1zOlFJlJUf/8jDHWIC/aZWfqfKcdCXJABEBAAGJ
AR8EGAECAAkFAlzCrMkCGwwACgkQdHJ4EVwGl2udrQf7BNyKjbubaEYn/QS6PcWc
t844PwI9ar+Ury/6ugf3wYnWYy0P/pcjWn1HHoHrpvE7vGjDHCW5EUAmDIrRJnVL
7NIuk6wTRDM6b5G4hsLCt1nBBxi8vlqJ3JCGysNqnfXl00MLxJW9cuDhAMNNUahw
rOjdQH01BqPii2NIds72xifjRCZzV/TDwp1Hut22lh03KmSsYbX9Uo207Dm/WHyP
hiWL2zMnx8wy91mCkgiRqJc2TIy+Oly1awJDh0mQd/gRoBhmunnQGZYWb4YhYNDy
5cCrYDN7W7Aqq+kvb4Te5US+xUKDGbgdaI51ihO21PcySUOjge7aR8funvQDZq/i
SA==
=yFbB
-----END PGP PUBLIC KEY BLOCK-----
"""

_GPG_REL = """
-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: GnuPG v2.0.22 (GNU/Linux)

mQENBFhoRoABCADKHEzVeogKYIt/oCafsqqHnHAIWZwGuviNYkxwjUyiveWS7co+
lGh1YcdW/8qh4ObKNxXFHCPJoHTNVl9rpjqA4SxdipxtEx4uWtI1A0Ba7Wz5JUqC
p4oSph82uXgzOg+/4Oz/PtapK6xPOVhDhpEcetb0PRVOsHk5Zm4duIVcNjyDeJ60
8GVEMYDAdTz8jaxtjxhXygasyz3waAXThRX5+geNM8zeQsRRXUtlSKT+12eyrLaQ
+K2+uFKvvuwMA89Wh91GJYTvPJLwuCr3x2j+RmVqEJ+TahzKVCpRiZyWO7TnjUks
dA3dyFbldvdThKXduvHxZajYlerCeqopVj9fABEBAAG0MWNpc2NvIChJT1MtWFIt
U1ctUlBNLnJlbCkgPHRhYy1zdXBwb3J0QGNpc2NvLmNvbT6JASIEEwEIABYFAlho
RoAJENoLWkaDS8b1AhsDAhkBAABc/Af9FoSisiwWYCcifhee6s7VQ6fhrmXg23fh
iqd8Ldlh0Tjktt5Kx/HPwug9RRYyFgwaOsbR71/rDiSQvqyhoQSdKWOR7ko3O+ZL
HXAcrcCbC8dYDcZwT7YGZJR0No4c7b2rfizf08E+/qJAKRQ7AlBTPDGaZn1PkRXa
POgCctMKQu4fIK1mEvk9qw2Aj8pDifVfr/6aqGZSFEVJzdpHL4mR7YeUcSB24y4A
Oe8s7hdV6N2Xw24Oprp4VS5Ozmz+pIEQ6FNXfQiLgD1YePbUrp4JvXljU7RmSoqM
EeFf9478GDE0PsxBzUj37MXPBi4LGDdnB/U1fsW6H0K+faMuYP+Alg==
=jdOr
-----END PGP PUBLIC KEY BLOCK-----
"""

_GPG_DUMMY = """
-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: GnuPG v2.0.22 (GNU/Linux)

mI0EYw4skQEEANT3uzAUUR8Cul7/EKyCsBybpCL2Mj95skTeYZmgEAfOfRSsbiuf
oY5+R1ge0j/5SZlTxj13zA4PqZCKGSxRZXZrY3hxbNXSV1SA3FJunLRGz2nirWWw
xgpRDZMwG+0zZEi6P1t3N1g2vvBRzVfg4pUZs5QrqPGmzU3t8BKtlq6TABEBAAG0
SER1bW15IEtleSAoRHVtbXkga2V5IGZvciB0ZXN0IHB1cnBvc2VzLCBkbyBub3Qg
dXNlKSA8ZG9ub3R1c2VAY2lzY28uY29tPoi5BBMBAgAjBQJjDiyRAhsDBwsJCAcD
AgEGFQgCCQoLBBYCAwECHgECF4AACgkQmXDiVJeSktCOfgQA0o3ssfwXjRwRt/2P
WsWioaHzlXW/F1YowQNjrvvxXaQfv1xzqT6GBiFgVgeNoUlNixRJmMxwnXdHlZMk
v6RCCJEWNwaY2pBByNblL2A1zaopCIQW2LXyy+KILXpwBoJpJ7QfaD3jahUJxFae
7wGJR5vfZvlBxP0OmWkaaxi5wkq4jQRjDiyRAQQA2ALoiXWoRs09tl7JkYIa5k/w
+U4jpwzQt3mWGGvd1Ws2gSTf+2TorOxssEup6U9JJ+vevgFChWjAaqN/q6+pDS/u
GPQgYS+n2g+rjTyZtZauYFjrAYtMfkgEJsi6Jo216QcuKgwi+Ao09vonfLuyoxUu
Z7+n4ed9x2oRp//Tje8AEQEAAYifBBgBAgAJBQJjDiyRAhsMAAoJEJlw4lSXkpLQ
MvID/R+pGoTtBQJTfEEmT0m/XNI9by3JzA/L6IWBiH8qf4drP7LjqPTFS2muaQSx
wNGSCHGaEEpxzsaqium5WaCuY4o062jY2YCtjSiL+BiB7+p4OeH47N3ALkNecJfP
QNFokRClFJc6J/M7tyD13r39DurnAyf7zz8QAWAXRW1KExMC
=6Wp3
-----END PGP PUBLIC KEY BLOCK-----
"""

_GPG_KEY_FOR = {
    KeyType.REL: _GPG_REL,
    KeyType.DEV: _GPG_DEV,
    KeyType.DUMMY: _GPG_DUMMY,
}
_KEY_FILENAME_FOR = {
    KeyType.REL: "rel.gpg",
    KeyType.DEV: "dev.gpg",
    KeyType.DUMMY: "dummy.gpg",
}

_LOG_BREAK = "-" * 80


class CheckFailuresError(Exception):
    """Error when there are check failures."""


class _VerifySignaturesError(Exception):
    """
    Error if there are failures verifying signatures.

    .. attribute:: failures

        The set of packages with failures.

    """

    def __init__(self, failures: Set[_packages.Package]) -> None:
        super().__init__(failures)
        self.failures = failures


class _VerifyDependenciesError(Exception):
    """
    Error for a dependency check failure.

    .. attribute:: pid

        The name of the pid that the dependency check was performed for.

    .. attribute:: output

        The output from the rpm command.

    """

    def __init__(self, pid: str, output: str) -> None:
        super().__init__(pid, output)
        self.pid = pid
        self.output = output


@contextlib.contextmanager
def _init_rpm_db() -> Iterator[pathlib.Path]:
    """Initialize a temporary directory to use as an RPM database."""
    with tempfile.TemporaryDirectory(prefix="rpm_checks_db_") as tmp_dir:
        db_dir = pathlib.Path(tmp_dir)
        yield db_dir


def _verify_dependencies(
    pid: str,
    pid_pkgs: Set[_packages.Package],
    pkg_to_file: Mapping[_packages.Package, pathlib.Path],
) -> Optional[_VerifyDependenciesError]:
    """
    Call rpm to verify the dependencies of the given packages

    :param pid:
         The name of the PID that the dependencies are being verified for.

    :param pid_pkgs:
        The paths to the set of packages on 'pid'.

    :param pkg_to_file:
        Mapping of package to the filepath on disk.

    :returns:
        A _VerifyDependenciesError if the depedencies are not met, else None
    """
    pid_pkg_paths = {pkg_to_file[pkg] for pkg in pid_pkgs}
    _logger.debug("Checking dependencies for PID %s", pid)
    with _init_rpm_db() as db_dir:
        try:
            _runrpm.check_install(db_dir, sorted(pid_pkg_paths))
        except _runrpm.CheckInstallError as e:
            return _VerifyDependenciesError(pid, e.exc.output)

    return None


def _pkg_has_invalid_signature(
    pkg: _packages.Package,
    pkg_to_file: Mapping[_packages.Package, pathlib.Path],
    db_dir: pathlib.Path,
) -> Optional[_packages.Package]:
    """
    Check if the given package has an invalid signature.

    :param pkg
        The package to verify signatures for.

    :param pkg_to_file:
        A mapping of package to filepath.

    :param db_dir
        Directory to use as an RPM database.

    :returns:
        'pkg' if the package has an invalid signature, None otherwise.
    """
    pkg_path = pkg_to_file[pkg]

    _logger.debug("Verifying signature for %s", str(pkg_path))
    try:
        output = _runrpm.check_signature(db_dir, pkg_path)
    except _runrpm.CheckSignatureError:
        # If the command fails then add the package as a failure
        return pkg
    else:
        # The command can still succeed even if the package doesn't
        # have the correct signatures. The command only checks the
        # signatures present in the RPM match the imported keys, so if
        # the RPM isn't signed at all then the command will succeed.
        # If the appropriate signature type is not in the output then
        # this is an error.
        #
        # Pylint errors with unsupported-membership-test for the below:
        #   "Value 'output' doesn't support membership test"
        # even though 'output' is a string. Calling str on it silences the
        # warning.
        if "RSA/SHA256 Signature" not in str(output):
            return pkg

    return None


def _import_key(filename: str, key: str, db_dir: pathlib.Path) -> None:
    """
    Create the key file and import it to the RPM database.

    :param filename:
        The filename to write the key to.

    :param key:
        The key to write to the file.

    """
    key_file = db_dir / filename
    with open(key_file, "w") as f:
        f.write(key)

    _runrpm.import_key(db_dir, key_file)


def _verify_signatures(
    pkgs: Set[_packages.Package],
    pkg_to_file: Mapping[_packages.Package, pathlib.Path],
    sig_type: KeyType,
) -> None:
    """
    Verify the signatures of the given packages.

    :param pkgs:
        The set of packages to verify signatures for.

    :param pkg_to_file:
        A mapping of package to filepath.

    :param sig_type:
        Which key the package was signed with (and should be checked against)

    """

    key_filename = _KEY_FILENAME_FOR[sig_type]
    key = _GPG_KEY_FOR[sig_type]
    failures = set()
    with _init_rpm_db() as db_dir:
        _import_key(key_filename, key, db_dir)

        possible_failures = _multiprocessing.map_helper(
            functools.partial(
                _pkg_has_invalid_signature,
                pkg_to_file=pkg_to_file,
                db_dir=db_dir,
            ),
            sorted(pkgs, key=str),
        )
        for possible_failure in possible_failures:
            if possible_failure is not None:
                failures.add(possible_failure)

    if failures:
        raise _VerifySignaturesError(failures)


def _fmt_depcheck_error(
    error: _VerifyDependenciesError, verbose: bool
) -> List[str]:
    """
    Format the dependency check failure messages and filter out unneeded.

    :param msgs:
        The set of error messages from rpm.

    :param verbose:
        Boolean indicating whether verbose option has been specified.

    :return:
        The new formatted set of error messages.

    """
    msgs = error.output.splitlines()
    if not verbose:
        out_msgs = []
        # Missing dependency errors from rpm look like:
        #   xr-foo >= 1.2.3v1.0.0-1 is needed by xr-bar
        # or if no version is specified then just:
        #   xr-foo is needed by xr-bar
        for msg in msgs:
            # In general we want to suppress Cisco(libfoo.so) errors as
            # they are generally not as clear as missing dependencies on
            # rpm names. Solving other dependencies generally solves all
            # the cisco library dependencies as well. Filter these
            # dependencies out unless all of the dependency failures are
            # from these cisco library dependencies.
            if not (
                msg.lstrip().startswith("Cisco(lib") and "is needed by" in msg
            ):
                out_msgs.append(msg)

        # If we've filtered anything out, then make sure that there are
        # some meaningful error messages left. If there aren't any other
        # error messages then just use everything.
        #
        # We specifically look for the "is needed by" string as this
        # indicates a missing dependency error. We can't just check if
        # out_msgs is empty because rpm adds a header to the full message.
        if out_msgs != msgs and not any(
            "is needed by" in msg for msg in out_msgs
        ):
            out_msgs = msgs

        # Add a footer if any messages have been omitted.
        if out_msgs != msgs:
            omitted_msg_count = len(msgs) - len(out_msgs)
            out_msgs.append(
                f"{omitted_msg_count} dependency check errors omitted; "
                "use the --verbose-dep-check option to see all errors."
            )
    else:
        out_msgs = msgs

    return [
        f"Dependency check failures on PID {error.pid}. RPM output:",
        *out_msgs,
        _LOG_BREAK,
    ]


def _fmt_signature_error(error: _VerifySignaturesError) -> List[str]:
    """Format signature failures into a list of messages to log."""
    assert error.failures

    msgs = [
        "Signature verification failures:",
        "  The following packages are not signed with the same key as the "
        "base ISO or are not signed at all:",
    ]
    for failure in sorted(error.failures, key=str):
        msgs.append(f"    {str(failure)}")
    msgs.append(_LOG_BREAK)
    return msgs


def _log_error_msgs(msgs: Sequence[str]) -> None:
    """Log the given error messages."""
    for msg in msgs:
        _logger.error(msg)


def _log_from_errors(
    errors: Sequence[Union[_VerifyDependenciesError, _VerifySignaturesError]],
    verbose_depcheck: bool,
) -> None:
    """
    Log any errors from package checks.

    :param errors:
        Collection of errors found during package checks.

    :param verbose_depcheck:
        Boolean indicating whether to use verbose output for dependency check
        messages or not.

    """
    msgs = []
    for error in errors:
        if isinstance(error, _VerifyDependenciesError):
            msgs.extend(_fmt_depcheck_error(error, verbose_depcheck))
        else:
            assert isinstance(error, _VerifySignaturesError)
            msgs.extend(_fmt_signature_error(error))

    _log_error_msgs(msgs)


def run(
    pkgs: _blocks.GroupedPackages,
    pkg_to_file: Mapping[_packages.Package, pathlib.Path],
    verbose_depcheck: bool,
    sig_type: KeyType,
) -> None:
    """
    Check the dependencies and signatures of the given packages.

    This function performs the following checks on the chosen set of packages:
    - Dependency checks: verifies that the set of packages on each PID form an
      installable set. That is that the rpm dependencies
      (requires/provides/conflicts) are met for all of the given packages.
    - Signature checks: verifies that all of the packages are signed with the
      required key.

    :param pkgs:
        The packages to check dependencies for grouped into logical blocks.

    :param pkg_to_file:
        Mapping of package to the filepath on disk.

    :param verbose_depcheck:
        Boolean indicating whether to have verbose dependency check output.

    :param sig_type:
        What sort of key the packages in the ISO were signed with

    """
    errors: List[Union[_VerifyDependenciesError, _VerifySignaturesError]] = []

    # Run the dependency checking per PID. A different set of packages is
    # installed on each pid so we need to perform the dependency check for
    # each set of packages on each pid individually.
    pid_to_pkgs = pkgs.get_pkgs_per_pid()
    possible_errors = _multiprocessing.starmap_helper(
        functools.partial(_verify_dependencies, pkg_to_file=pkg_to_file),
        sorted(pid_to_pkgs.items()),
    )
    for possible_error in possible_errors:
        if possible_error is not None:
            errors.append(possible_error)

    try:
        for group in _isoformat.PackageGroup:
            if group.verify_signatures:
                _verify_signatures(
                    pkgs.get_all_pkgs(group), pkg_to_file, sig_type
                )
    except _VerifySignaturesError as e:
        errors.append(e)

    if errors:
        _log_from_errors(errors, verbose_depcheck)
        raise CheckFailuresError(
            "There are failures from checking dependencies and signatures of "
            "chosen packages."
        )
