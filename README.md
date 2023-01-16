# gisobuild toolkit for IOS-XR

## Usage

```
usage: gisobuild.py [-h] [--iso ISO] [--repo REPO [REPO ...]]
                    [--bridging-fixes BRIDGE_FIXES [BRIDGE_FIXES ...]]
                    [--xrconfig XRCONFIG] [--ztp-ini ZTP_INI] [--label LABEL]
                    [--no-label] [--out-directory OUT_DIRECTORY]
                    [--create-checksum] [--yamlfile CLI_YAML] [--clean]
                    [--pkglist PKGLIST [PKGLIST ...]] [--script SCRIPT]
                    [--docker] [--x86-only] [--migration] [--optimize]
                    [--full-iso]
                    [--remove-packages REMOVE_PACKAGES [REMOVE_PACKAGES ...]]
                    [--skip-usb-image] [--copy-dir COPY_DIRECTORY]
                    [--clear-bridging-fixes] [--verbose-dep-check] [--debug]
                    [--isoinfo ISOINFO] [--image-script IMAGE_SCRIPT]
                    [--version]

Utility to build Golden ISO for IOS-XR.

optional arguments:
  -h, --help            show this help message and exit
  --iso ISO             Path to Mini.iso/Full.iso file
  --repo REPO [REPO ...]
                        Path to RPM repository. For LNT, user can specify
                        .rpm, .tgz, .tar filenames, or directories. RPMs are
                        only used if already included in the ISO, or specified
                        by the user via the --pkglist option.
  --bridging-fixes BRIDGE_FIXES [BRIDGE_FIXES ...]
                        Bridging rpms to package. For EXR, takes from-release
                        or rpm names; for LNT, the user can specify the same
                        file types as for the --repo option.
  --xrconfig XRCONFIG   Path to XR config file
  --ztp-ini ZTP_INI     Path to user ztp ini file
  --label LABEL, -l LABEL
                        Golden ISO Label
  --no-label            Indicates that no label at all should be added to the
                        GISO
  --out-directory OUT_DIRECTORY
                        Output Directory
  --create-checksum     Write a file with the checksum and size of the output
                        file(s)
  --yamlfile CLI_YAML   Cli arguments via yaml
  --clean               Delete output dir before proceeding
  --pkglist PKGLIST [PKGLIST ...]
                        Packages to be added to the output GISO. For eXR:
                        optional rpm or smu to package. TPA(non-cisco) rpm can
                        also be provided in this option. For LNT: either full
                        package filenames or package names for user
                        installable packages can be specified. Full package
                        filenames can be specified to choose a particular
                        version of a package, the rest of the block that the
                        package is in will be included as well. Package names
                        can be specified to include optional packages in the
                        output GISO.
  --key-requests KREQLIST [KREQLIST...]
                        Key Requests to be added to the Output GISO.
  --docker, --use-container
                        Build GISO in container environment.Pulls and run pre-
                        built container image to build GISO.
  --version             Print version of this script and exit

EXR only build options:
  --script SCRIPT       Path to user executable script executed as part of
                        bootup post activate.
  --x86-only            Use only x86_64 rpms even if other architectures are
                        applicable.
  --migration           To build Migration tar only for ASR9k
  --optimize            Optimize GISO by recreating and resigning initrd
  --full-iso            To build full iso only for xrv9k

LNT only build options:
  --remove-packages REMOVE_PACKAGES [REMOVE_PACKAGES ...]
                        Remove RPMs, specified in a comma separated list.
                        These are matched against user installable package
                        names, and must be the whole package name, e.g: xr-bgp
  --skip-usb-image      Do not build the USB image
  --copy-dir COPY_DIRECTORY
                        Copy built artefacts to specified directory if
                        provided. The specified directory must already exist,
                        be writable by the builder and must not contain a
                        previously built artefact with the same name.
  --clear-bridging-fixes
                        Remove all bridging bugfixes from the input ISO
  --verbose-dep-check   Verbose output for the dependency check.
  --debug               Output debug logs to console
  --isoinfo ISOINFO     User specified isoinfo executable to use instead of
                        the default version
  --image-script IMAGE_SCRIPT
                        User specified image.py script to be used for
                        packing/unpacking instead of the version extracted
                        from the ISO. It will not be inserted into the GISO.
                        Intended for debugging purposes only.

```

## Description

Typically Cisco releases IOS-XR software as a mini/base ISO which contains
mandatory IOS-XR packages for a given platform and separately a set of
optional packages and software patches for any bug fixes (SMU). 
Optional package and SMU are in RPM packaging format.

The Golden ISO tool creates an ISO containing the full contents of
the mini/base ISO together with optional packages and SMU of the user's
choice. Once the Golden ISO is created it can be used either for iPXE booting
a router or used for SU (system upgrade) from the current running version to
a new version of IOS-XR.

## Requirements

This tool has the following executable requirements:
* python3 >= 3.6
* rpm >= 4.14
* cpio >= 2.10
* gzip >= 1.9
* createrepo_c
* file
* isoinfo
* mkisofs
* mksquashfs
* openssl
* unsquashfs
* 7z (Optional - but functionality may be reduced without)

It also requires the following Python (>= 3.6) modules:
* dataclasses
* defusedxml
* distutils
* packaging
* rpm
* yaml

# Invocation

This tool can be run natively on a Linux host if the dependencies above are met.
Alternatively, the tool can also be run on a Linux system with Docker enabled
and the ability to pull the published 'cisco-xr-gisobuild' image from Docker
Hub, in which case the above dependencies are met by the published image.

To run natively on a Linux host, the following distributions have been tested.
* Alma Linux 8
* Fedora 34
* Debian 11.2

On a native Linux system, which does not have all dependencies met,
the tool dependencies can be installed on supported distributions above
by running the following command (possibly via sudo)
              
    ./setup/prep_dependency.sh

To load and run the pre-built cisco-xr-gisobuild docker image, ensure that the
docker service is enabled and it's possible to pull and run published docker
images.

Run the following command to check docker service parameters.

    docker info

Running the tool:

To run natively on a linux host which has dependency requirements met:

    ./src/gisobuild.py --iso <input iso> --repo <rpm repo1 rpm_repo2> \
        --pkglist <pkg1 pkg2 pkg3> --bridging-fixes <smu1 smu2 smu3> \
        --xrconfig <config.cfg> --ztp-ini <ztp.ini> --script <user_script.sh> \
        --label <label> --out-directory <out_directory> --clean

The tool has a helpful usage info which lists down the options supported.

When user does not want to specify the inputs via cli, an alternate would be to populate the yaml file template 
provided in the toolkit and pass the same via:

    ./src/gisobuild.py --yamlfile <input_yaml_cfg>

To override any input in the yaml config file, please use the corresponding cli option and parameter.

    ./src/gisobuild.py --yamlfile <input_yaml_cfg> --label <new_label>

The above command will override the label specified in yaml file with new option provided via cli option --label.

When the host machine does not have its dependency met, but allows pulling and running docker images, enable 
docker option in yaml file to true and run as (possible with GISO for eXR variants of IOS-XR):

    ./src/gisobuild.py --yamlfile <input_yaml_cfg>

where input_yaml_cfg has:

    docker: true

Output:

The corresponding GISO and build logs are available under the directory
specified in `--out-directory`. The default if not specified is
`<pwd>/output_gisobuild`.


# Note: older version of the tool

The legacy eXR python2-based gisobuild utility is available at:

 https://github.com/ios-xr/gisobuild/tree/gisobuild-exr-legacy

The command to pull the above code base is:

    git clone  --branch gisobuild-exr-legacy https://github.com/ios-xr/gisobuild/
