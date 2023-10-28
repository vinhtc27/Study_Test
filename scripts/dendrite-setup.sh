#!/bin/bash

server=$1
setup_type=$2

cd /matrix
ulimit -Sn `ulimit -Hn`

# Reset environment
ansible-playbook -i inventory/hosts setup.yml --tags=stop

# setup_type either may be default 'full-setup' or a variant like 'full-setup-sqlite'
full_setup_prefix="full-setup"

if [ "${setup_type:0:${#full_setup_prefix}}" = "$full_setup_prefix" ]; then
    # Sometimes Ansible does not correctly remove old worker services on Synapse
    systemctl reset-failed matrix*
    rm -rf postgres synapse conduit dendrite sqlite/*

    # Ansible setup
    sed -i 's/matrix_homeserver_implementation: synapse/matrix_homeserver_implementation: dendrite/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_homeserver_implementation: conduit/matrix_homeserver_implementation: dendrite/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_synapse_workers_enabled: true/matrix_synapse_workers_enabled: false/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_synapse_redis_enabled: true/matrix_synapse_redis_enabled: false/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_redis_enabled: true/matrix_redis_enabled: false/g' inventory/host_vars/$server/vars.yml

    # Ansible fails setup if enabled and not using synapse...
    sed -i 's/matrix_synapse_ext_password_provider_shared_secret_auth_enabled: true/matrix_synapse_ext_password_provider_shared_secret_auth_enabled: false/g' inventory/host_vars/$server/vars.yml

    if [ "$setup_type" = "full-setup-sqlite" ]; then
        sed -i 's/matrix_postgres_enabled: true/matrix_postgres_enabled: false/g' inventory/host_vars/$server/vars.yml
    else
        sed -i 's/matrix_postgres_enabled: false/matrix_postgres_enabled: true/g' inventory/host_vars/$server/vars.yml
    fi

    ansible-playbook -i inventory/hosts setup.yml --tags=setup-all

    if [ "$setup_type" = "full-setup-sqlite" ]; then
        # Need Docker to mount directory for storing SQLite DB
        yes | cp backup/matrix-dendrite.service /etc/systemd/system/matrix-dendrite.service
    fi

else # reset
    rm -rf postgres dendrite sqlite/*

    # Default 'reset' is postgres, otherwise value is 'reset-sqlite' currently
    if [ "$setup_type" = "reset" ]; then
        ansible-playbook -i inventory/hosts setup.yml --tags=setup-postgres
    fi

    ansible-playbook -i inventory/hosts setup.yml --tags=setup-dendrite

    if [ "$setup_type" = "reset-sqlite" ]; then
        # Need Docker to mount directory for storing SQLite DB
        yes | cp backup/matrix-dendrite.service /etc/systemd/system/matrix-dendrite.service
    fi
fi

# Server specific config setup
yes | cp backup/dendrite.yaml dendrite/config/dendrite.yaml

ansible-playbook -i inventory/hosts setup.yml --tags=start
exit
