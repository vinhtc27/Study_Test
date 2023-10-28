#!/bin/env python3

import resource
import logging

from locust import task, constant
from locust import events
from locust.runners import MasterRunner

import gevent
from matrixuser import MatrixUser

# Preflight ###############################################

@events.init.add_listener
def on_locust_init(environment, **_kwargs):
    # Increase resource limits to prevent OS running out of descriptors
    resource.setrlimit(resource.RLIMIT_NOFILE, (999999, 999999))

    # Register event hooks
    if not isinstance(environment.runner, MasterRunner):
        print(f"Registered 'load_users' handler on {environment.runner.client_id}")
        environment.runner.register_message("load_users", MatrixInviteAcceptorUser.load_users)


###########################################################


class MatrixInviteAcceptorUser(MatrixUser):
    wait_time = constant(0)

    worker_id = None
    worker_users = []

    @staticmethod
    def load_users(environment, msg, **_kwargs):
        MatrixInviteAcceptorUser.worker_users = iter(msg.data)
        MatrixInviteAcceptorUser.worker_id = environment.runner.client_id
        logging.info("Worker [%s]: Received %s users", environment.runner.client_id, len(msg.data))

    @task
    def accept_invites(self):
        # Load the next user
        try:
            user = next(MatrixInviteAcceptorUser.worker_users)
        except StopIteration:
            # We can't shut down the worker until all users are registered, so return
            # early to stop this individual co-routine
            gevent.sleep(999999)
            return

        self.login_from_csv(user)

        if self.username is None or self.password is None:
            #print("Error: Couldn't get username/password")
            logging.error("Couldn't get username/password. Skipping...")
            return

        # Log in as this current user if not already logged in
        if self.user_id is None or self.access_token is None or \
            len(self.user_id) < 1 or len(self.access_token) < 1:
            
            self.login(start_syncing = False, log_request=True)

        # Call /sync to get our list of invited rooms
        self.sync()

        # Persist initial sync token for chat simulation
        token_update_request = { "username": self.username, "user_id": self.user_id,
                                 "access_token": self.access_token, "sync_token": self.sync_token }
        self.environment.runner.send_message("update_tokens", token_update_request)

        # self.invited_room_ids set is modified by the MatrixUser class after joining a room
        rooms_to_join = self.invited_room_ids.copy()

        logging.info("User [%s] has %d pending invites",
                     self.username, len(self.invited_room_ids))
        for room_id in rooms_to_join:
            retries = 3
            while retries > 0:
                result = self.join_room(room_id)

                if result is None:
                    logging.info("[%s] Could not join room %s (attempt %d). Trying again...",
                                 self.username, room_id, 4 - retries)
                    retries -= 1
                else:
                    break

            if retries == 0:
                logging.error("[%s] Error joining room %s. Skipping...", self.username, room_id)

