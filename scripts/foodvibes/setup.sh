. $(cd ${0%$(basename $0)} && pwd)/common.sh "${1}" 1

check_run_module() {
    local here=$1
    local tag=$2
    local modname=$3
    local run_module=$4
    local love_level=$5
    local rc=1

    (($run_module == 0)) && (($(get_value_boolean n "Install/update ${tag}? (y/n)") == 1)) && run_module=1
    if (($run_module == 1)); then
        ${here}/setup_${modname}.sh $log_level
        rc=$?
    else
        logger 0 "Skipped ${tag}"
        rc=0
    fi

    return $rc
}

typeset slug="FoodVibes"
typeset operation=""
typeset run_all=0
typeset run_module=0

logger 0 "${slug} setup started"

((rc == 0 && $(get_value_boolean n "Install/update ALL? (y/n)") == 1)) && run_all=1
((rc == 0)) &&
    {
        check_run_module $here "Key Vault" "key_vault" $run_all $log_level &&
            check_run_module $here "API" "api" $run_all $log_level &&
            check_run_module $here "UI" "ui" $run_all $log_level &&
            check_run_module $here "Database" "database" $run_all $log_level &&
            # check_run_module $here "FarmVibes.ai for deforestation images" "farmvibes" $run_all $log_level &&
            check_run_module $here "Start the back-end and front-end services" "launch" $run_all $log_level
        rc=$?
    }

check_status $rc "${slug} setup"
