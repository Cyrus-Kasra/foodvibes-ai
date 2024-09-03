. $(cd ${0%$(basename $0)} && pwd)/common.sh "${1}" "${2}"

install_farmvibes_ai() {
    logger 0 "Fetching source code and creating virtual environment..."

    cd $here/../../.. &&
        logger 0 "Installation directory is \"$(pwd)\"..." &&
        git clone https://github.com/microsoft/farmvibes-ai.git &&
        cd farmvibes-ai &&
        python -m venv .venv &&
        . .venv/bin/activate && {
        logger 1 "Virtual enviroment set up. Current directory is $(pwd)"
        logger 1 "Installing FarmVibes.ai..."

        bash ./resources/vm/setup_farmvibes_ai_vm.sh &&
            pip install ./src/vibe_core &&
            farmvibes-ai local setup && {
            logger 1 "Validating FarmVibes.ai installation..."

            python -m vibe_core.farmvibes_ai_hello_world &&
                farmvibes-ai local status
        }
    } && {
        logger 1 "Successful installation. FarmVibes.ai service is running."

        cat <<EOS

To interact with farmvibes-ai, enter the virtual environment using:
    cd farmvibes-ai
    . .venv/bin/activate

To stop service
    farmvibes-ai local stop

To start service
    farmvibes-ai local start

To view service status
    farmvibes-ai local status

To exit virtual environment
    deactivate
    cd ~-
EOS
    } ||
        logger 2 "Failed installation"
}

typeset slug_local="FarmVibes.ai for deforestation images setup"

logger 0 "${slug_local} started"

install_farmvibes_ai
rc=$?

check_status $rc "${slug_local}"
