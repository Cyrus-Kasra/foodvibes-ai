typeset -i rc=0
typeset -i log_level=${1:-0}
typeset -i main_script=${2:-0}
typeset -i password_length=10

logger() {
    typeset -i level=${1:-0} # -1: debug/0: normal/1: good/2: bad

    (($level < $log_level)) && return 0

    typeset prefix="0"
    typeset midfix=" "

    case "$1" in
    -1)
        prefix="34" # blue
        midfix=" - DEBUG - "
        ;;
    1)
        prefix="32" # green
        midfix=" - INFO - "
        ;;
    2)
        prefix="31" # red
        midfix=" - ERROR - "
        ;;
    *)
        prefix="33"
        ;;
    esac

    shift 1
    echo -e "\033[0m\033[${prefix}m$(date +"%Y-%m-%d %H:%M:%S,%3N")${midfix}$*\033[0m" >&2
}

check_status() {
    local -i rc_to_check=$1
    local message="$2"
    local flag=2
    local suffix="failed"

    ((rc_to_check == 0)) && {
        flag=0
        suffix="completed"
    }

    logger $flag "${message} ${suffix}"

    return $rc_to_check
}

get_value() {
    local default_value=$1 # $2-: prompt message
    local answer
    local default_value_display=" [${default_value}]"

    [[ -z "$default_value" ]] && default_value_display=""

    shift 1
    read -p "$*${default_value_display}: " answer
    echo "${answer:-${default_value}}"
}

get_value_boolean() {
    answer=$(get_value $*)

    case $answer in
    [Yy1Tt]*)
        echo 1
        ;;
    *)
        echo 0
        ;;
    esac
}

get_absolute_path() {
    local path=$1
    local basename=$(basename $path)

    echo "$(cd ${path%$basename} && pwd)/$basename"
}

get_env_file_entry() {
    local key=$1
    local env_file=$2
    local default_value="$3"
    local output=$(grep "^${key}=" ${env_file} | cut -d= -f2- | sed -e 's/"//g' -e 's/\r//g')
    echo "${output:-${default_value}}"
}

set_env_file_entry() {
    local key=$1
    local value="$2"
    local env_file=$3

    {
        grep -v "^${key}=" ${env_file}
        echo "${key}=\"${value}\"" | sed -e 's/\r//g'
    } >${env_file}.tmp && mv ${env_file}.tmp ${env_file} || {
        logger 2 "Failed to set key $key in ${env_file}"
        return 1
    }

    logger -1 "Key $key set in ${env_file}"
    return 0
}

get_entra_id_app_id() {
    local app_name=$1

    echo "$(az ad app list --query "[?displayName=='${app_name}'].appId" --output tsv)"
}

remove_old_azure_components() {
    local old_resource_group_name=$1
    local old_entra_id_app_name=$2

    [[ -n "$old_entra_id_app_name" ]] &&
        {
            local old_entra_id_app_id=$(get_entra_id_app_id $old_entra_id_app_name)

            [[ -n "$old_entra_id_app_id" ]] &&
                {
                    logger 0 "Deleting app registration \"$old_entra_id_app_name\"..."
                    ((log_level < 0)) && set -xv
                    az ad sp delete --id $old_entra_id_app_id >/dev/null 2>&1
                    az ad app delete --id $old_entra_id_app_id >/dev/null 2>&1
                    set +xv
                }
        }
    [[ -n "$old_resource_group_name" ]] && {
        logger 0 "Deleting resource group \"$old_resource_group_name\"..."
        ((log_level < 0)) && set -xv
        az group delete --name $old_resource_group_name --yes >/dev/null 2>&1
        set +xv
    }
}

reset_env_file_sub() {
    local env_file=$1
    local keys=$(echo "^$2" | sed -e 's/ /|^/g')

    egrep -v "${keys}" ${env_file} >${env_file}.tmp && mv ${env_file}.tmp ${env_file} || {
        logger 2 "Failed to set key $key in ${env_file}"
        return 1
    } && logger 1 "Keys reset in ${env_file}"

    return 0
}

reset_env_file() {
    local env_file=$1
    local env_file_ui=$2
    local env_file_keys=(
        "RESOURCE_GROUP_LOCATION"
        "RESOURCE_GROUP_NAME"
        "ENTRA_ID_APP_NAME"
        "KEY_VAULT_NAME"
        "DATABASE_SERVER"
        "DATABASE_IP_ADDR_START_"
        "DATABASE_IP_ADDR_END_"
        "BLOB_STORAGE_ACCT"
        "FARMVIBES_URL"
        "BINGMAPS_API_KEY"
        "APP_INSIGHTS_INSTRUMENTATION_KEY"
        "DATABASE_USERNAME"
        "DATABASE_PASSWORD"
        "ADMA_BASE_URL"
        "ADMA_PARTY_ID"
        "ADMA_AUTHORITY"
        "ADMA_CLIENT_ID"
        "ADMA_CLIENT_SECRET"
    )
    local env_file_ui_keys=(
        "VITE_CLIENT_ID"
        "VITE_AUTHORITY"
    )

    reset_env_file_sub $env_file "${env_file_keys[*]}" &&
        reset_env_file_sub $env_file_ui "${env_file_ui_keys[*]}" &&
        logger -1 "All keys reset in ${env_file} and ${env_file_ui}"

    return $?
}

get_set_file_entry() {
    local key=$1
    local var_name=$2
    local env_file=$3
    local default_value="$4"
    local tag="$5"
    local prompt=${6:-0}
    local value_in_envfile=0

    eval local value=\"\$$var_name\"

    [[ -z "$value" ]] && value=$(get_env_file_entry "$key" "$env_file" "$default_value")
    [[ -n "$tag" ]] && (($prompt == 1)) && value="$(get_value "$value" "Enter ${tag}")"

    eval $var_name=\"$value\"
    set_env_file_entry "$key" "$value" $env_file

    return $?
}

get_key_vault_secret() {
    local secret_name=$1
    local default_value=$2
    local secret_recs="$3"
    local secret_value="$(echo "$secret_recs" | grep "^${secret_name}=" | cut -d= -f2- | sed -e 's/"//g' -e 's/\r//g')"

    echo "${secret_value:-${default_value}}"
}

get_key_vault_secret_all() {
    local key_vault=$1
    local secret_names=$(az keyvault secret list --vault-name $key_vault --query "[].name" -o tsv | sed -e 's/\r//g' 2>/dev/null)

    for secret_name in $secret_names; do
        secret_value=$(az keyvault secret show --name "$secret_name" --vault-name $key_vault --query "value" -o tsv)
        echo "${secret_name}=${secret_value}"
    done
}

get_unique_id() {
    date +"-%H:%M:%S-%8N-%Y-%m-%d-%H:%M:%S-%8N" | sed -e 's/[-:]//g'
}

truncate_unique_id() {
    local input=${1-$(get_unique_id)}
    local maxlen=${2:-24}

    echo "$(echo "$input" | cut -c1-$(($maxlen - 1)))z"
}

make_storage_acct_name() {
    local env_file=$1
    local suffix=${2:-$(get_unique_id)}
    local output="$(get_env_file_entry BLOB_STORAGE_ACCT $env_file $(truncate_unique_id "fv-ssa-${suffix}"))"

    set_env_file_entry BLOB_STORAGE_ACCT "$output" $env_file &&
        echo "${output}"
}

generate_password() {
    local password

    # Ensure the password contains at least one upper, one lower, one digit, and one special character
    while true; do
        password=$(tr -dc 'A-Za-z0-9!@#%_+|:=' </dev/urandom | head -c $password_length)
        [[ "$password" =~ [A-Z] ]] && [[ "$password" =~ [a-z] ]] && [[ "$password" =~ [0-9] ]] && [[ "$password" =~ [\!@#%_+\|:=] ]] &&
            {
                echo "$password"
                break
            }
    done
}

check_password_complexity() {
    local password=$1
    local rc=1
    local err_level=2
    local msg="Invalid password"

    if ((${#password} < $password_length)); then
        msg="Password needs to be at least $password_length characters"
    elif ! [[ $password =~ [A-Z] ]]; then
        msg="Password must include at least one uppercase letter"
    elif ! [[ $password =~ [a-z] ]]; then
        msg="Password must include at least one lowercase letter"
    elif ! [[ $password =~ [0-9] ]]; then
        msg="Password must include at least one number"
    elif ! [[ $password =~ [\!\@\#\$\%\^\&\*\(\)\_\+\{\}\|\:\<\>\?\=] ]]; then
        msg="Password must include at least one special character"
    elif [[ $password =~ [[:space:]] ]]; then
        msg="Password must not include any whitespace characters"
    else
        rc=0
        err_level=1
        msg="Password meets complexity requirements"
    fi

    logger $err_level "$msg"

    return $rc
}

mask_value() {
    local value=$1
    local mask_char=${2:-"*"}

    echo "${value}" | sed -e "s/./${mask_char}/g"
}

check_tool() {
    tool="$1"
    command="${2}"

    logger -1 "Checking ${tool}..."
    eval $command 2 >/dev/null 2>&1 || {
        logger 2 "${tool} not found"
        return 1
    }
    return 0
}

check_tools() {
    local rc=1
    logger 0 "Checking tools..."

    check_tool "jq -- JSON parser" 'jq --version' &&
        check_tool "python" 'python --version' &&
        check_tool "python3" 'python3 --version' &&
        check_tool "pip" 'pip --version' &&
        check_tool "pip3" 'pip3 --version' &&
        check_tool "npm" 'npm --version' &&
        check_tool "yarn" 'npm --version' &&
        check_tool "az -- Azure CLI" 'az --version'
    rc=$?

    if (($rc == 0)); then
        logger 1 "All tools are installed"
    else
        logger 2 "Some tools are missing"
    fi

    return $rc
}

typeset here=$(dirname $(get_absolute_path $0))
typeset env_file=$(get_absolute_path "${here}/../../.env")
typeset env_file_ui=$(get_absolute_path "${here}/../../ui/.env")
typeset subscription_id=""
typeset username=""
typeset resource_group_location=""
typeset resource_group_name=""
typeset entra_id_app_name=""
typeset key_vault_name=""
typeset database_server=""
typeset database_name="foodvibes_db"
typeset blob_storage_acct=""
typeset blob_container_name="foodvibes-blobcntr" # No underscores allowed
typeset adma_base_url=""
typeset adma_party_id=""
typeset adma_authority=""
typeset adma_client_id=""
typeset adma_client_secret=""
typeset farmvibes_url=""
typeset bingmaps_api_key=""
typeset foodvibes_app_insights_instrumentation_key=""
typeset database_username=""
typeset database_password=""
typeset database_ip_addr_start_0=""
typeset database_ip_addr_end_0=""

[[ -f /home/vscode/.bashrc ]] &&
    {
        . /home/vscode/.bashrc
    }
if (($main_script == 1)); then
    check_tools
    rc=$?
else
    rc=0
fi
(($rc == 0)) && [[ -z "$(az account show)" ]] &&
    {
        az login
        rc=$?
    }
(($rc == 0)) && {
    [[ -f $env_file ]] || touch $env_file
    [[ -f $env_file_ui ]] || touch $env_file_ui
    [[ -f $env_file && -f $env_file_ui ]] &&
        {
            (($main_script == 1)) && (($(get_value_boolean n "Reset all Azure config? (y/n)") == 1)) &&
                {
                    remove_old_azure_components "$(get_env_file_entry RESOURCE_GROUP_NAME $env_file)" "$(get_env_file_entry ENTRA_ID_APP_NAME $env_file)"
                    reset_env_file $env_file $env_file_ui
                }

            typeset update_all=$main_script
            resource_group_location=$(get_env_file_entry RESOURCE_GROUP_LOCATION $env_file)
            [[ -n "$resource_group_location" ]] && (($main_script == 1)) && (($(get_value_boolean n "Update all config entries? (y/n)") == 0)) && update_all=0

            typeset suffix=$(get_unique_id)
            typeset ipaddr_base="$(curl -4 ifconfig.me 2>/dev/null | cut -d. -f1-3)."
            get_set_file_entry RESOURCE_GROUP_LOCATION resource_group_location $env_file "West US" "Resource Group location" $update_all &&
                get_set_file_entry RESOURCE_GROUP_NAME resource_group_name $env_file "foodvibes-rg-${suffix}" &&
                get_set_file_entry ENTRA_ID_APP_NAME entra_id_app_name $env_file "fv-app-${suffix}" &&
                get_set_file_entry KEY_VAULT_NAME key_vault_name $env_file $(truncate_unique_id "fv-kv-${suffix}") &&
                get_set_file_entry DATABASE_SERVER database_server $env_file "fv-dbsrv-${suffix}" &&
                get_set_file_entry DATABASE_IP_ADDR_START_0 database_ip_addr_start_0 $env_file "${ipaddr_base}0" &&
                get_set_file_entry DATABASE_IP_ADDR_END_0 database_ip_addr_end_0 $env_file "${ipaddr_base}255" &&
                get_set_file_entry BLOB_STORAGE_ACCT blob_storage_acct $env_file $(truncate_unique_id "fvssa${suffix}") &&
                get_set_file_entry FARMVIBES_URL farmvibes_url $env_file "" "Farmvibes.ai URL" $update_all &&
                get_set_file_entry BINGMAPS_API_KEY bingmaps_api_key $env_file "" "Bing Maps API Key" $update_all &&
                get_set_file_entry APP_INSIGHTS_INSTRUMENTATION_KEY foodvibes_app_insights_instrumentation_key $env_file "" "AppInsights instrumentation key" $update_all &&
                {
                    database_password=$(get_env_file_entry DATABASE_PASSWORD $env_file $(generate_password))
                    typeset token_based_db_access=0

                    (($update_all == 1)) && (($(get_value_boolean n "Use token-based database access? (y/n)") == 1)) && token_based_db_access=1

                    if (($token_based_db_access == 1)); then
                        rc=0
                    else
                        get_set_file_entry DATABASE_USERNAME database_username $env_file "myadminuser" "Database username" $update_all &&
                            [[ -n $database_username ]] &&
                            {
                                typeset -i password_ok=0
                                typeset update_password=$update_all

                                while (($password_ok == 0)); do
                                    get_set_file_entry DATABASE_PASSWORD database_password $env_file "$database_password" \
                                        "Database password (min $password_length chars & at least include 1 upper, 1 lower, 1 number & 1 char from \"! @ # % _ + | : =\" set)" $update_password &&
                                        check_password_complexity "$database_password" && password_ok=1 || update_password=1
                                done

                                [[ -n $database_password ]] && rc=$?
                            }
                    fi
                }

            (($rc == 0)) &&
                {
                    rc=1
                    get_set_file_entry ADMA_BASE_URL adma_base_url $env_file "" "ADMA base URL" $update_all &&
                        get_set_file_entry ADMA_PARTY_ID adma_party_id $env_file "" "ADMA party ID (the ID of client in ADMA)" $update_all &&
                        {
                            typeset adma_authority=$(get_env_file_entry ADMA_AUTHORITY $env_file)
                            typeset get_adma_credentials=0

                            [[ -z "$adma_authority" ]] && (($update_all == 1)) &&
                                (($(get_value_boolean n "Use APP registration (not Entra ID) to connect to ADMA? (y/n)") == 1)) && get_adma_credentials=1

                            get_set_file_entry ADMA_AUTHORITY adma_authority $env_file "" "ADMA authority" $get_adma_credentials &&
                                get_set_file_entry ADMA_CLIENT_ID adma_client_id $env_file "" "ADMA client ID (blank if using Azure Authentication to connect to ADMA)" $get_adma_credentials &&
                                get_set_file_entry ADMA_CLIENT_SECRET adma_client_secret $env_file "" "ADMA client secret (blank if using Azure Authentication to connect to ADMA)" $get_adma_credentials

                        }
                }
        }

    rc=$?
}
(($rc == 0)) && {
    az account show >/dev/null 2>&1 || az login
    rc=$?
}
(($rc == 0)) && {
    typeset az_show_account="$(az account show | jq '.id,.user.name' | sed -e 's/"//g')"

    subscription_id=$(echo "$az_show_account" | sed -n 1p)
    username=$(echo "$az_show_account" | sed -n 2p)

    [[ -z "$username" ]] &&
        {
            rc=1
            logger 2 "Username not found"
        }
}
(($rc == 0 && $main_script == 0)) && {
    logger 0 \
        "Current Configuration:\n" \
        "\nSubscription ID::::::::: ${subscription_id}" \
        "\nUsername:::::::::::::::: ${username}" \
        "\nResource Group Location: ${resource_group_location}" \
        "\nResource Group Name::::: ${resource_group_name}" \
        "\nEntra ID App Name::::::: ${entra_id_app_name}" \
        "\nKey Vault Name:::::::::: ${key_vault_name}" \
        "\nDatabase Server Name:::: ${database_server}" \
        "\nDatabase Instance Name:: ${database_name}" \
        "\nDatabase Username::::::: ${database_username}" \
        "\nDatabase Password::::::: $(mask_value "$database_password")" \
        "\nBLOB Storage Account:::: ${blob_storage_acct}" \
        "\nBLOB Container Name::::: ${blob_container_name}" \
        "\nFarmVibes.ai URL:::::::: ${farmvibes_url}" \
        "\nBing Maps API Key::::::: ${bingmaps_api_key}" \
        "\nAppInsights Instr. Key:: ${foodvibes_app_insights_instrumentation_key}" \
        "\nADMA Base URL::::::::::: ${adma_base_url}" \
        "\nADMA Party ID::::::::::: ${adma_party_id}" \
        "\nADMA Authority:::::::::: ${adma_authority}" \
        "\nADMA Client ID:::::::::: ${adma_client_id}" \
        "\nADMA Secret::::::::::::: $(mask_value "adma_client_secret")"
}
