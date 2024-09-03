. $(cd ${0%$(basename $0)} && pwd)/common.sh "${1}" "${2}"

typeset slug_local="API setup"

logger 0 "${slug_local} started"

(($rc == 0)) && cd ${here}/../.. &&
    {
        if [[ -f requirements.txt ]]; then
            pip install -r requirements.txt
            rc=$?
        else
            rc=0
        fi
    }

check_status $rc "${slug_local}"
