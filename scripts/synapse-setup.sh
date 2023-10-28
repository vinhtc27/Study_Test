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

    # Ansible setup (default)
    sed -i 's/matrix_homeserver_implementation: conduit/matrix_homeserver_implementation: synapse/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_homeserver_implementation: dendrite/matrix_homeserver_implementation: synapse/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_synapse_workers_enabled: false/matrix_synapse_workers_enabled: true/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_synapse_redis_enabled: false/matrix_synapse_redis_enabled: true/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_postgres_enabled: false/matrix_postgres_enabled: true/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_redis_enabled: false/matrix_redis_enabled: true/g' inventory/host_vars/$server/vars.yml

    # Modify previous setup for Synapse configuration variants
    if [ "$setup_type" = "full-setup-sqlite" ] || [ "$setup_type" = "full-setup-postgres-noworkers" ]; then
        sed -i 's/matrix_synapse_workers_enabled: true/matrix_synapse_workers_enabled: false/g' inventory/host_vars/$server/vars.yml
        sed -i 's/matrix_synapse_redis_enabled: true/matrix_synapse_redis_enabled: false/g' inventory/host_vars/$server/vars.yml
        sed -i 's/matrix_redis_enabled: true/matrix_redis_enabled: false/g' inventory/host_vars/$server/vars.yml
    fi

    if [ "$setup_type" = "full-setup-sqlite" ]; then
        sed -i 's/matrix_postgres_enabled: true/matrix_postgres_enabled: false/g' inventory/host_vars/$server/vars.yml
    fi

    # Ansible fails setup if enabled and not using synapse...
    sed -i 's/matrix_synapse_ext_password_provider_shared_secret_auth_enabled: false/matrix_synapse_ext_password_provider_shared_secret_auth_enabled: true/g' inventory/host_vars/$server/vars.yml

    ansible-playbook -i inventory/hosts setup.yml --tags=setup-all

    # Server specific config setup
    if [ "$setup_type" = "full-setup-sqlite" ]; then
        yes | cp backup/homeserver.yaml synapse/config/homeserver.yaml

        # Need Docker to mount directory for storing SQLite DB
        yes | cp backup/matrix-synapse.service /etc/systemd/system/matrix-synapse.service
    else
        # Ansible playbook is currently missing rc_joins_per_room rate-limiting config
        yes | cp backup/homeserver_postgres.yaml synapse/config/homeserver.yaml
    fi

else # reset
    rm -rf postgres sqlite/*

    if ! [ "$setup_type" = "reset-sqlite" ]; then
        ansible-playbook -i inventory/hosts setup.yml --tags=setup-postgres
    fi
fi

# Server specific config setup
if [ "$setup_type" = "full-setup-sqlite" ] || [ "$setup_type" = "reset-sqlite" ]; then
    yes | cp backup/homeserver.db sqlite/homeserver.db
    chown 988:1000 sqlite/homeserver.db
fi

ansible-playbook -i inventory/hosts setup.yml --tags=start
exit
