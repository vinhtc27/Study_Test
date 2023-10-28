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
    sed -i 's/matrix_homeserver_implementation: synapse/matrix_homeserver_implementation: conduit/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_homeserver_implementation: dendrite/matrix_homeserver_implementation: conduit/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_synapse_workers_enabled: true/matrix_synapse_workers_enabled: false/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_synapse_redis_enabled: true/matrix_synapse_redis_enabled: false/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_postgres_enabled: true/matrix_postgres_enabled: false/g' inventory/host_vars/$server/vars.yml
    sed -i 's/matrix_redis_enabled: true/matrix_redis_enabled: false/g' inventory/host_vars/$server/vars.yml

    # Ansible fails setup if enabled and not using synapse...
    sed -i 's/matrix_synapse_ext_password_provider_shared_secret_auth_enabled: true/matrix_synapse_ext_password_provider_shared_secret_auth_enabled: false/g' inventory/host_vars/$server/vars.yml

    ansible-playbook -i inventory/hosts setup.yml --tags=setup-all

else # reset
    rm -rf conduit sqlite/*
    ansible-playbook -i inventory/hosts setup.yml --tags=setup-conduit
fi

# Server specific config setup
if [ "$setup_type" = "full-setup-sqlite" ] || [ "$setup_type" = "reset-sqlite" ]; then
    sed -i 's/database_backend = "rocksdb"/database_backend = "sqlite"/g' conduit/config/conduit.toml
fi

ansible-playbook -i inventory/hosts setup.yml --tags=start
exit
