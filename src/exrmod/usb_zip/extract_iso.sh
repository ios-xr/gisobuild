#!/bin/bash  
# 
# HELP
#
# Extract an ISO a single file at a time without need for root. Needs isoinfo.
#
# Usage: isoread -i <file> -o <outdir>
#
#   -i
#   -iso
#   --iso <imagename>   : Name of ISO to read.
# 
#   -o
#   -out
#   --out <dir>         : Directory to extract to.
#
#   -d
#   -debug
#   --debug             : Debug.
#
# (based on http://korenofer.blogspot.mx/2008/08/how-to-extract-iso-file-with-bash-shell.html)
#
# END_OF_HELP

ORIGINAL_ARGS="$0 $*"
ISOINFO="isoinfo"

help()
{
    cat $0 | sed '/^# HELP/,/^# END_OF_HELP/!d' | grep -v HELP | sed -e 's/^..//g' | sed 's/^#/ /g'
}

setup_colors()
{
    DULL=0
    FG_BLACK=30
    FG_RED=31
    FG_GREEN=32
    FG_YELLOW=33
    FG_BLUE=34
    FG_MAGENTA=35
    FG_CYAN=36
    FG_WHITE=37
    FG_NULL=00
    BG_NULL=00
    ESC=ESET="${ESC}${DULL};${FG_WHITE};${BG_NULL}m"
    BLACK="${ESC}${DULL};${FG_BLACK}m"
    RED="${ESC}${DULL};${FG_RED}m"
    GREEN="${ESC}${DULL};${FG_GREEN}m"
    YELLOW="${ESC}${DULL};${FG_YELLOW}m"
    BLUE="${ESC}${DULL};${FG_BLUE}m"
    MAGENTA="${ESC}${DULL};${FG_MAGENTA}m"
    CYAN="${ESC}${DULL};${FG_CYAN}m"
    WHITE="${ESC}${DULL};${FG_WHITE}m"
}

err() {
    echo -n `date`
    echo ": ${RED}ERROR: $*${RESET}"
}

log() {
    echo -n `date`
    echo ": ${GREEN}$*${RESET}"
}

extract_iso()
{
    local ISO_FILE=$1
    local OUT_DIR=$2
    local DIR=
    local ERR=

    #
    # Extract the ISO contents
    #
    local TMP=`mktemp`
    $ISOINFO -R -l -i ${ISO_FILE} > $TMP
    if [ $? -ne 0 ]
    then
        err "Failed to extract $ISO_FILE"
        exit 1
    fi

    if [ ! -f $TMP ]
    then
        err "Failed to make $TMP"
        exit 1
    fi

    exec< $TMP

    while read LINE
    do
        if [ "$OPT_DEBUG" != "" ]
        then
            echo "$LINE"
        fi

        #
        # Ignore empty lines
        #
        if [ "$LINE" = "" ]
        then
            continue
        fi

        #
        # Look for directory lines
        #
        local DIR_PREFIX="Directory listing of "

        if [[ $LINE == "${DIR_PREFIX}"* ]]
        then
            #
            # Remove the "Directory listing of " prefix
            #
            DIR=`echo $LINE | sed s/"${DIR_PREFIX}"//g`

            mkdir -p ${OUT_DIR}/$DIR
        else
            #
            # Ignore directories
            #
            if [[ $LINE = "d"* ]]
            then
                continue
            fi

            #
            # Strip leading fields
            #
            local FILE=`echo $LINE | cut -d" " -f12`

            #
            # $ISOINFO to leave .. as a file sometimes
            #
            if [ "$FILE" = ".." ]
            then
                continue
            fi

            #
            # Extract the file
            #
            local DIR_FILE=${DIR}${FILE}
            local OUT_DIR_FILE=${OUT_DIR}${DIR}${FILE}

            if [ "$OPT_DEBUG" != "" ]
            then
                log "$ISOINFO -R -i ${ISO_FILE} -x ${DIR_FILE}"
            fi

            $ISOINFO -R -i ${ISO_FILE} -x ${DIR_FILE} > ${OUT_DIR_FILE}
            if [ $? -ne 0 ]
            then
                err "Failed to extract $DIR_FILE"
                ERR=1
            fi

            if [ "$OPT_DEBUG" != "" ]
            then
                /bin/ls -lart ${OUT_DIR_FILE}
            fi
        fi
    done

    /bin/rm -f $TMP

    if [ "$ERR" != "" ]
    then
        err "Failed to extract all files"
        exit 1
    fi
}

ISO=$1
OUT=$2

read_options()
{
    shift
    while [ "$#" -ne 0 ];
    do
        case $1 in
        -i | -iso | --iso )
            shift
            OPT_ISO=$1
            ;;

        -o | -out | --out )
            shift
            export OPT_OUT_DIR=$1
            ;;

        -d | -debug | --debug )
            export OPT_DEBUG=1
            ;;
        esac

        shift
    done
}

main()
{
    setup_colors

    read_options $ORIGINAL_ARGS

    if [ "$OPT_ISO" = "" ]
    then
        help
        err "Need an ISO"
        exit 1
    fi

    if [ "$OPT_OUT_DIR" = "" ]
    then
        help
        err "Need an output destination"
        exit 1
    fi

    extract_iso $OPT_ISO $OPT_OUT_DIR
}

main
