#!/bin/env python3

import logging
import resource

from locust import task, constant
from locust import events
from locust.runners import MasterRunner

import gevent
from matrixuser import MatrixUser

# Preflight ####################################################################

@events.init.add_listener
def on_locust_init(environment, **_kwargs):
    # Increase resource limits to prevent OS running out of descriptors
    resource.setrlimit(resource.RLIMIT_NOFILE, (999999, 999999))

    # Register event hooks
    if not isinstance(environment.runner, MasterRunner):
        print(f"Registered 'load_users' handler on {environment.runner.client_id}")
        environment.runner.register_message("load_users", MatrixRegisterUser.load_users)

################################################################################


class MatrixRegisterUser(MatrixUser):
    wait_time = constant(0)
    worker_id = None
    worker_users = []

    @staticmethod
    def load_users(environment, msg, **_kwargs):
        MatrixRegisterUser.worker_users = iter(msg.data)
        MatrixRegisterUser.worker_id = environment.runner.client_id
        logging.info("Worker [%s] Received %s users", environment.runner.client_id, len(msg.data))

    @task
    def register_user(self):
        # Load the next user who needs to be registered
        try:
            user = next(MatrixRegisterUser.worker_users)
        except StopIteration:
            # We can't shut down the worker until all users are registered, so return
            # early to stop this individual co-routine
            gevent.sleep(999999)
            return

        self.username = user["username"]
        self.password = user["password"]

        if self.username is None or self.password is None:
            #print("Error: Couldn't get username/password")
            logging.error("Couldn't get username/password. Skipping...")
            return

        retries = 3
        while retries > 0:
            # Register with the server to get a user_id and access_token
            self.register()

            # The register() method sets user_id and access_token
            if self.user_id is not None and self.access_token is not None:
                # Save access tokens
                user_update_request = { "username": self.username, "user_id": self.user_id,
                                        "access_token": self.access_token, "sync_token": "" }
                self.environment.runner.send_message("update_tokens", user_update_request)
                return
            else:
                logging.info("[%s] Could not register user (attempt %d). Trying again...",
                             self.username, 4 - retries)
                retries -= 1

        logging.error("Error registering user %s. Skipping...", self.username)
