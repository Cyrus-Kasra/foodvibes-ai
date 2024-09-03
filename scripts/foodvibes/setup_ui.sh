. $(cd ${0%$(basename $0)} && pwd)/common.sh "${1}" "${2}"

typeset slug_local="UI setup"

logger 0 "${slug_local} started"

((rc == 0)) && cd ${here}/../../ui && yarn install

check_status $rc "${slug_local}"
