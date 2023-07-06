# ------------------------------------------------------------------------------

"""Helper utility definitions to extract gISO information.

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

import argparse
import datetime
import getpass
import logging
import os
import pathlib
import shutil
import shlex
import socket
import stat
import subprocess
import sys
import tempfile

from logging import handlers
from typing import Any, Dict, List, Tuple

from . import lnt_gisoglobals as gisoglobals

_log = logging.getLogger(__name__)


# Path to image.py and signature
_IMAGE_PY = "tools/image.py"
_IMAGE_SIG = "tools/image.py.signature"

# Tooling information that the user may have specified on the CLI.
_isoinfo = "isoinfo"
_image_script = None

# Key info
#
# LNT key info obtained by booting a router and running:
# /usr/bin/keyctl pipe %user:sec-rel-key
# /usr/bin/keyctl pipe %user:sec-dev-key
#
# LNT on Fretta key info obtained by running:
# openssl x509 -in tools/code-sign/NCS-55xx_rel_cert.der -inform der -noout -pubkey
# openssl x509 -in tools/code-sign/NCS-55xx_dev_cert.der -inform der -noout -pubkey
#
# For DEV images, DEV and REL keys are allowed
_MIME_HARDCODED_KEY_INFO = {
    "sec-rel-key": """-----BEGIN CERTIFICATE-----
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
89MNrU60YRq0HTirdggYbWuaRhyR/cg4lg==
-----END CERTIFICATE-----
""",
    "sec-dev-key": """-----BEGIN CERTIFICATE-----
MIIGRTCCBS2gAwIBAgIJAJCyMbBW2bGYMA0GCSqGSIb3DQEBCwUAMDkxGTAXBgNV
BAMMEElPUy1YUi1TVy1TRUMtQ0ExDDAKBgNVBAsMA0RFVjEOMAwGA1UECgwFQ2lz
Y28wHhcNMTgxMDEwMTU1NDA5WhcNMzYwMjI1MTU1NDA5WjA5MRkwFwYDVQQDDBBJ
T1MtWFItU1ctU0VDLUNBMQwwCgYDVQQLDANERVYxDjAMBgNVBAoMBUNpc2NvMIIB
IjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAn/aDB/2TY2wxhB415FOQ3/wf
PYjlgcLZ3CGlkDjBUzwr5+7YU7GUR+Lb6cYdwvuCqnQftSuj6YwiqBRntVPjOYtE
VFhe/OMbNa0RGfPPEsPVeo4mJ3m7cSwvLxBTpMD+eFGYgMKo4ei7Fx8HiZ4eq7Vc
PpHHCHSTOFDv/NSnVky2eCjh9whKHpAEpWdLoWWWNfh6FVM6AQ5uly2flL4j/YJu
jb7Sb2qLfrxdoU4itcLSUeosrLE4DM3WrczbMyBtb4742hRZ9qBY5r9dRSMQL+o4
0RTuPyyJNqeqBvuEcF6koY0gz0p/5K4qAuoVSfU+CKopW9GC/V8BGeRiM12R3wID
AQABo4IDTjCCA0owEgYDVR0TAQH/BAgwBgEB/wIBADAOBgNVHQ8BAf8EBAMCAQYw
ggEiBgNVHQ4EggEZBIIBFTCCARGAAQGBggEABo81Jxvu0wheW8aYZDNh6HdKzjO/
uL6LeabEKOAVxygAcSEdEPOmHgJw04lUmqhlFPMYWvP6kjY/Dz0qIRphFu76jOIv
M9bv7pfsFzarOVhfYE/HwsJz8nwXYRBQRx9zCVJJFc/52aERsYfvDEZg2LmUtxPA
D3w86XtwrtQ/+LkHs6Hddn4vs/ed4EgTYaiSBc0yiLEaVSgGNRqUSnLs7BCqxLRe
VeM07Nwq/z3WAUZ9rhhw4InH05tQPb0cXslP+uXfmtkHOQ8PHGw0mZ56kan2HfFz
mVGyIuVhEiChVGoSZ5oxi3V9ZhS0v+EvAj6I3lqCMyjmAClfKBtb3OsYkYIETqSV
4YMCCAAwRAYDVR0fBD0wOzA5oDegNYYzaHR0cDovL3d3dy5jaXNjby5jb20vc2Vj
dXJpdHkvcGtpL2NybC9jcmNhc2VjeHIuY3JsMEQGCCsGAQUFBwEBBDgwNjA0Bggr
BgEFBQcwAYYoaHR0cDovL3Rvb2xzLmNpc2NvLmNvbS9wa2kvc2VydmljZXMvb2Nz
cDCCAXAGA1UdIwSCAWcwggFjgIIBFTCCARGAAQGBggEABo81Jxvu0wheW8aYZDNh
6HdKzjO/uL6LeabEKOAVxygAcSEdEPOmHgJw04lUmqhlFPMYWvP6kjY/Dz0qIRph
Fu76jOIvM9bv7pfsFzarOVhfYE/HwsJz8nwXYRBQRx9zCVJJFc/52aERsYfvDEZg
2LmUtxPAD3w86XtwrtQ/+LkHs6Hddn4vs/ed4EgTYaiSBc0yiLEaVSgGNRqUSnLs
7BCqxLReVeM07Nwq/z3WAUZ9rhhw4InH05tQPb0cXslP+uXfmtkHOQ8PHGw0mZ56
kan2HfFzmVGyIuVhEiChVGoSZ5oxi3V9ZhS0v+EvAj6I3lqCMyjmAClfKBtb3OsY
kYIETqSV4YMCCAChPaQ7MDkxGTAXBgNVBAMMEElPUy1YUi1TVy1TRUMtQ0ExDDAK
BgNVBAsMA0RFVjEOMAwGA1UECgwFQ2lzY2+CCQCQsjGwVtmxmDANBgkqhkiG9w0B
AQsFAAOCAQEAfEkz2hZGmy3kyZld+uOClLvuJtcIscLwkdqThwpS4PNIZ4+V029O
kXklxoiQIrEuO+DW1Z/t852lrEMVhXfixyUshmBHzHAkmozt0YP3vEcEm5su+Pn3
eMamersdxwQFiXzS8FzimRzBvWMEIn3WxKLDya3kFopjuz9p1Zv7x1lgNR/znkpl
aI723KA9mPENOj6zL0ajV47Is9AkpEUppVEj0sSGF0ObE5/CBXDKxuDoDXkPfnkx
kd+fcEY+x6m5xItIxgF3zKtbDwW8VPVcxXW5dmyrqXoHs4RTXQ1eLcjzFfV05ken
052GURRzCna/VmfVw/iQ2idtQBZASqPChw==
-----END CERTIFICATE-----""",
}
_DIGEST_HARDCODED_KEY_INFO = {
    "ncs55xx-rel-key": """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA8DmphVQ8F0dQOTS5f0lj
SOXNfITTzyyvUzCJCpvmQgquKJrk0QjwNV7WKJvXnzM2RvyXxvRBKgsZ77TwtWi/
ZdiDNDWid7hOSum1s+HRHwOZw+Pqwf6QYeWqvVJnvjSYryUiLTmZPkTL0SvIiFD5
X/kG2Qpb96/bNtF8CUedw4lrb7lT0pZrtZMx3c2kKgD3HbWHS8V1pOlLvNkTGAPe
5OXO8Y4lBuh3RonLpBvqYJYH5AAOK0YXPMVILHYVjDyCxiWR+jBI40bb3wSD+Pt4
krn2YUjMAGJ61GaLccnMRxbMYjOVtNQ5GdDwdtEX6IV557df0SpSH5bjEhAtO9Mh
9wIDAQAB
-----END PUBLIC KEY-----""",
    "ncs55xx-dev-key": """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA38kRZvRO/178qibNlp22
R6YJNOHUPqyyHzxxayeftsr34IKHjkpidUjBKcjVMwbNf2usLoS6iwLlPlOgHYey
RMa6PgWIUi8wknlsc/6Isi/6r7azqx1T98w+zRI8t2MxTpjV3/EcksqlXr+v0p1N
mQMxzQb1JxepqPenONBo7fB3wRsWIXq+Rr7ZWbP7fWJb7Oe8ZvWb6I03plOLRIyg
rSlDF8Bt2kR8vofbwrpD0ShnF9y2OIB3lJDldMfbf3jCLZWoeFLoULocGsQpvPO2
HRSXWwkolXXT/W7m1EDAHqbWPjZfkbugw719RGZUY/SeGXmovhpgz54g5OWDRo1X
yQIDAQAB
-----END PUBLIC KEY-----""",
}


class VerificationFailedError(Exception):
    """Failed to verify the image.py script"""

    def __init__(self) -> None:
        """Initialise a IosInfoError"""
        super().__init__("Failed to verify signature of image.py")


class CopyDirInvalidError(Exception):
    """The copy dir doesn't exist"""

    def __init__(self, copy_dir: str):
        """Initialise a CopyDirInvalidError"""
        super().__init__(
            "The directory {} to copy build artefacts into must already exist "
            "and be writeable before gisobuild can be run".format(copy_dir)
        )


class CopyBuildArtefactError(Exception):
    """Failed to copy a build artefact to its destination"""

    def __init__(self, source: str, dest: str, error: str):
        """Initialise a CopyBuildArtefactError"""
        super().__init__(
            "Could not copy the build artefact {} to {}: {}".format(
                source, dest, error
            )
        )


class BuildArtefactInCopyDirError(Exception):
    """
    One of the build artefacts that will be copied is already in the copy dir

    """

    def __init__(self, artefact: str, copy_dir: str):
        """Initialise a BuildArtefactInCopyDirError"""
        super().__init__(
            "Cannot copy build artefacts; {} is already present in {}".format(
                artefact, copy_dir
            )
        )


class ISOInfoError(Exception):
    """Failed to extract file from ISO"""

    def __init__(self, cmd: List[str], error: str):
        """Initialise a IosInfoError"""
        super().__init__(
            "Failed to extract file from ISO with command {}: {}".format(
                cmd, error
            )
        )


class QueryISOError(Exception):
    """Failed to query ISO content"""

    def __init__(self, error: str) -> None:
        """Call parent's initialiser with a suitable error message"""
        super().__init__("Failed to query ISO: {}".format(error))


# -----------------------------------------------------------------------------
# Other utility functions
#
def generate_buildinfo_mdata() -> Dict[str, str]:
    """
    Generate a dictionary containing the GISO build info fields of the JSON
    metadata

    :returns:
        Dictionary of build info
    """
    new_mdata = {}

    # Populate build info fields
    new_mdata[
        gisoglobals.LNT_GISO_BUILD_TIME
    ] = datetime.datetime.now().strftime("%b %d, %Y %H:%M:%S")
    new_mdata[gisoglobals.LNT_GISO_BUILD_CMD] = " ".join(sys.argv)

    new_mdata[gisoglobals.LNT_GISO_BUILDER] = getpass.getuser()
    new_mdata[gisoglobals.LNT_GISO_BUILD_HOST] = socket.gethostname()
    new_mdata[gisoglobals.LNT_GISO_BUILD_DIR] = os.getcwd()

    return new_mdata


def check_copy_dir(copy_dir: str) -> None:
    """
    Verify that the specified copy directory exists, is a directory, and is
    writeable.

    :param copy_dir:
        Directory to check
    """
    if not os.path.isdir(copy_dir) or not os.access(copy_dir, os.W_OK):
        raise CopyDirInvalidError(copy_dir)


def copy_artefacts_to_dir(artefacts: List[str], copy_dir: str) -> None:
    """
    Copy build artefacts to the specified directory, erroring if already
    present

    :param artefact_dir:
        Directory containing build artefacts

    :param copy_dir:
        Directory to copy artefacts to
    """
    existing_artefacts = os.listdir(copy_dir)
    for item in artefacts:
        if os.path.basename(item) in existing_artefacts:
            raise BuildArtefactInCopyDirError(os.path.basename(item), copy_dir)
    for item in artefacts:
        try:
            shutil.copy2(item, copy_dir)
        except OSError as error:
            raise CopyBuildArtefactError(item, copy_dir, str(error)) from error


def extract_file_from_iso(
    iso: str, filepath: str, tmp_dir: str, *, error_on_empty: bool = True
) -> str:
    """
    Extracts a named file from the ISO and places it in a temporary
    directory for later use.

    Note that this function is used to extract the image.py script from the
    ISO and so must not attempt to run any image script itself. See
    image.Image.extract_file() if the image script is already known.

    :param iso:
        The path to the ISO
    :param filepath:
        Path to the file in the ISO we want to extract
    :param tmp_dir:
        The temporary dir in which to place the extracted file
    :param error_on_empty:
        Indicates whether to check the size of the file, and error if it is
        size 0.
    :returns:
        The path to the extracted file
    """

    iso_path = os.path.join(tmp_dir, "iso", filepath)
    if not os.path.isdir(os.path.dirname(iso_path)):
        os.makedirs(os.path.dirname(iso_path), exist_ok=True)

    with open(iso_path, "w") as output_f:
        cmd = [get_isoinfo(), "-R", "-i", iso, "-x", "/" + filepath]
        try:
            subprocess.check_call(cmd, stdout=output_f, stderr=output_f)
        except subprocess.CalledProcessError as error:
            raise ISOInfoError(cmd, str(error)) from error

    if error_on_empty and not os.path.getsize(iso_path):
        # File is empty, isoinfo couldn't find the file to extract in
        # the ISO (or it was empty): this is an error
        cmd = [get_isoinfo(), "-R", "-l", "-i", iso]
        output = subprocess.check_output(cmd)
        print(output)
        raise FileNotFoundError(
            "Could not find file within ISO file: {}".format(iso_path)
        )

    return iso_path


def _check_signature_internal(
    base_file: str,
    sig_file: str,
    cert: str,
    cert_name: str,
    type_str: str,
    cmd_format: str,
    success_str: str,
) -> bool:
    """
    Wrapper for checking the signature of the file.

    :param base_file:
        The file to verify

    :param sig_file:
        The signature file to verify against

    :param cert:
        Contents of the certificate being verified

    :param cert_name:
        Name of the certificate being verified

    :param type_str:
        Debug string indicating what type of signature is being checked.

    :param cmd_format:
        String to be used to create the command. Contains variable names:
            base_file, sig_file, cert_file

    :param success_str:
        String to confirm success.

    :returns:
        True if the validation is successful, False otherwise

    """
    verify_success = False
    with tempfile.NamedTemporaryFile(mode="w") as cert_fileobj:
        cert_fileobj.write(cert)
        cert_fileobj.flush()
        cmd = shlex.split(
            cmd_format.format(
                base_file=base_file,
                sig_file=sig_file,
                cert_file=cert_fileobj.name,
            )
        )
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as exc:
            _log.debug(
                "Verification of %s by %s %s: %s failed to verify: "
                "returncode: %s, output: %s",
                base_file,
                cert_name,
                type_str,
                sig_file,
                exc.returncode,
                exc.stdout,
            )
        else:
            # A successful run indicates that verification has succeeded.
            # However, an additional check of success_str in the
            # output is possible.

            if success_str in output.decode("utf-8"):
                _log.debug(
                    "Verification of %s %s successful", base_file, type_str
                )
                verify_success = True

    return verify_success


def _check_signature_digest(
    base_file: str, sig_file: str, cert: str, cert_name: str
) -> bool:
    """
    Checks the signature of a file as if it is a digest based signature

    :param base_file:
        The file to verify

    :param sig_file:
        The signature file to verify against

    :param cert:
        Contents of the certificate being verified

    :param cert_name:
        Name of the certificate being verified

    :returns:
        True if the validation is successful, False otherwise

    """
    return _check_signature_internal(
        base_file,
        sig_file,
        cert,
        cert_name,
        "digest",
        "/usr/bin/openssl dgst -sha512 -verify {cert_file}"
        " -signature {sig_file} {base_file}",
        "Verified OK",
    )


def _check_signature_mime(
    base_file: str, sig_file: str, cert: str, cert_name: str
) -> bool:
    """
    Checks the signature of a file as if it is a MIME based signature

    :param base_file:
        The file to verify

    :param sig_file:
        The signature file to verify against

    :param cert:
        Contents of the certificate being verified

    :param cert_name:
        Name of the certificate being verified

    :returns:
        True if the validation is successful, False otherwise

    """
    return _check_signature_internal(
        base_file,
        sig_file,
        cert,
        cert_name,
        "MIME",
        "openssl cms -verify -binary -inform DER -in {sig_file}"
        " -content {base_file} -CAfile {cert_file} -out "
        "/dev/null",
        "Verification successful",
    )


def _verify_image_script(image_py: str, image_sig: str) -> bool:
    """
    Verify the signature of the image.py script

    :param image_py:
        The path to the image.py script

    :param image_sig:
        The image.py signature in the ISO

    :returns:
        True if the script is DEV-signed; False otherwise

    """
    # When verifying the ISO, we don't know what sort of ISO it is - or how
    # it's signed. Therefore, we have to loop through all the possible
    # keys/certificates until we have verified the ISO.
    #
    # The MIME keys are used on general LNT platforms, whereas the DIGEST keys
    # are solely for LNT-on-Fretta (because the Fretta system used a different
    # form of security). Because more platforms (both types of platform, and
    # likely numbers of actual systems) are general LNT - we do the MIME
    # signature first (with the REL key first, to make the script quicker for
    # customers!)
    #
    # If there is a way to determine the platform for a GISO (without first
    # having to access, i.e verify, the image.py), then this function should
    # be cleaned up to only query the keys for the ISO's platform.

    verified = False
    _log.debug(
        "Verifying image.py using both sec-rel-key and sec-dev-key keys so"
        " expect one of them to fail."
    )
    dev_signed = False
    for user_id, key in _MIME_HARDCODED_KEY_INFO.items():
        if not verified:
            verified = _check_signature_mime(image_py, image_sig, key, user_id)
            if verified and user_id == "sec-dev-key":
                dev_signed = True

    if not verified:
        for user_id, key in _DIGEST_HARDCODED_KEY_INFO.items():
            if not verified:
                verified = _check_signature_digest(
                    image_py, image_sig, key, user_id
                )
                if verified and user_id.endswith("-dev-key"):
                    dev_signed = True

    if not verified:
        # Neither the dev or release keys were verified so raise an error
        raise VerificationFailedError()

    return dev_signed


def extract_image_py_sig(iso: str, tmp_dir: str) -> Tuple[str, bool]:
    """
    Extract the image.py script from the ISO, verify the signature,
    and return its path

    :param iso:
        The path to the iso file

    :param tmp_dir:
        Temporary directory to store intermediate files

    :returns:
        Path to image.py, and a boolean indicating whether it was dev-signed

    """
    _log.debug("Extracting image.py to %s", tmp_dir)
    iso_script = extract_file_from_iso(iso, _IMAGE_PY, tmp_dir)
    signature = extract_file_from_iso(iso, _IMAGE_SIG, tmp_dir)
    dev_signed = _verify_image_script(iso_script, signature)

    # Update the current permissions to execute image.py
    perms = os.stat(iso_script)
    os.chmod(iso_script, perms.st_mode | stat.S_IEXEC)

    # If the user has specified an image.py to use in the command line
    # arguments, then use that.
    iso_script = get_image_script(iso_script)

    return (iso_script, dev_signed)


def get_groups_with_attr(
    groups: List[Dict[str, Any]], attribute: str
) -> List[str]:
    """
    Select groups with the specified attribute from the provided list

    :param groups:
        Group data, as a parsed json object

    :param attribute:
        Name of attribute to check for

    :returns:
        List of names of groups with the specified attribute
    """
    matching_groups = []
    for group in groups:
        try:
            for attr in group["attrs"]:
                if attr["name"] == attribute:
                    matching_groups.append(group["name"])
        except KeyError as error:
            group_str = (
                " for group {}".format(group["name"])
                if "name" in group.keys()
                else ""
            )
            raise QueryISOError(
                "Invalid ISO metadata{}".format(group_str)
            ) from error
    return matching_groups


def xml_strip_ns(xml: Any) -> None:
    """
    Strip the namespace from an XML file for more readable XML parsing.

    :param xml:
        The XML to be stripped

    """
    try:
        xml.tag = xml.tag.rsplit("}", 1)[1]
    except Exception:
        pass
    for x in xml:
        xml_strip_ns(x)


def init_logging(
    log_dir: str, log_file: str, *, debug: bool = False, disable: bool = False,
) -> logging.Logger:
    """
    Initialize stderr and debug file logging.

    Adds two handlers to the root logger:
      - Handler to output errors to stderr
      - Handler to output debug to the given (rotating) file.

    If used, should be called before any loggers are written to.

    :param log_dir:
        The directory to create the log_file in to.

    :param log_file:
        Logfile to write to

    :returns root_logger:
        Logger that will be used for this file

    """
    # Record log location for use elsewhere e.g. calling image.py
    log_file = os.path.join(log_dir, log_file)
    log_path = pathlib.Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Define a handler which writes ERROR messages or higher to stderr.
    stderr_formatter = logging.Formatter("%(message)s")
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(stderr_formatter)
    stderr_handler.setLevel(logging.DEBUG if debug else logging.ERROR)

    # Define a handler which writes DEBUG messages or higher to a
    # rotating log file.
    debug_formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d %(name)-24s %(levelname)-6s %(message)s",
        datefmt="%m-%d %H:%M:%S",
    )
    debug_handler = handlers.RotatingFileHandler(
        log_file, maxBytes=50000000, backupCount=10
    )

    debug_handler.setFormatter(debug_formatter)
    debug_handler.setLevel(logging.DEBUG)

    # If the log file already exists, roll over so a new log file is
    # created for each run.
    if os.path.isfile(log_file) and os.path.getsize(log_file) > 0:
        debug_handler.doRollover()

    # Get the root logger, set to DEBUG to handle all messages, and
    # add both handlers to it.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(stderr_handler)
    root_logger.addHandler(debug_handler)

    if disable:
        # Still allow error messages to be output - so we just disable warning
        # and below.
        logging.disable(logging.WARNING)

    return root_logger


def get_isoinfo() -> str:
    """Returns the isoinfo executable to use."""
    return _isoinfo


def get_image_script(iso_script: str) -> str:
    """
    Returns the image.py script to use.

    This will be the iso_script passed in, unless the user has specified
    otherwise on the CLI.

    """
    if _image_script:
        return _image_script
    else:
        return iso_script


def set_user_specified_tools(args: argparse.Namespace) -> None:
    """Update the tools depending on whether the user has specified them."""
    global _isoinfo
    global _image_script

    if args.isoinfo:
        _isoinfo = args.isoinfo
        _log.info(
            "User has specified to use the following isoinfo exectuable: %s",
            _isoinfo,
        )

    if args.image_script:
        _image_script = args.image_script
        _log.info(
            "User has specified to use the following image.py script: %s",
            _image_script,
        )


def add_wrappers_to_path() -> None:
    """
    Prepend PATH with the location where wrappers around standard tools are
    kept.

    """
    wrappers_path = str(
        pathlib.Path(os.path.abspath(__file__)).parents[1] / "wrappers"
    )

    if not wrappers_path in os.environ["PATH"]:
        os.environ["PATH"] = wrappers_path + os.pathsep + os.environ["PATH"]
