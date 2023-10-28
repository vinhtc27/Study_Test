#!/bin/env python3

import csv
import json
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
        environment.runner.register_message("load_users", MatrixRoomCreatorUser.load_users)

@events.test_start.add_listener
def on_test_start(environment, **_kwargs):
    if not isinstance(environment.runner, MasterRunner):
        user_reader = csv.DictReader(open("users.csv", "r", encoding="utf-8"))

        # Load our list of rooms to be created
        logging.info("Loading rooms list")
        rooms = {}
        with open("rooms.json", "r", encoding="utf-8") as rooms_jsonfile:
            rooms = json.load(rooms_jsonfile)
        logging.info("Success loading rooms list")

        # Now we need to sort of invert the list
        # We need a list of the rooms to be created by each user,
        # with the list of other users who should be invited to each
        MatrixRoomCreatorUser.worker_rooms_for_users = {}
        for room_name, room_users in rooms.items():
            first_user = room_users[0]
            user_rooms = MatrixRoomCreatorUser.worker_rooms_for_users.get(first_user, [])
            room_info = {
                "name": room_name,
                "users": room_users[1:]
            }
            user_rooms.append(room_info)
            MatrixRoomCreatorUser.worker_rooms_for_users[first_user] = user_rooms

###############################################################################


class MatrixRoomCreatorUser(MatrixUser):
    wait_time = constant(0)

    worker_id = None
    worker_users = []
    worker_rooms_for_users = {}

    # Indicates the number of users who have completed their room creation task
    num_users_rooms_created = 0

    @staticmethod
    def load_users(environment, msg, **_kwargs):
        MatrixRoomCreatorUser.worker_users = iter(msg.data)
        MatrixRoomCreatorUser.worker_id = environment.runner.client_id
        logging.info("Worker [%s]: Received %s users", environment.runner.client_id, len(msg.data))

    @task
    def create_rooms_for_user(self):
        # Load the next user for room creation
        try:
            user = next(MatrixRoomCreatorUser.worker_users)
        except StopIteration:
            # We can't shut down the worker until all users are registered, so return
            # early to stop this individual co-routine
            gevent.sleep(999999)
            return

        self.login_from_csv(user)

        if self.username is None or self.password is None:
            #print("Error: Couldn't get username/password")
            logging.error("[%s]: Couldn't get username/password. Skipping...",
                          MatrixRoomCreatorUser.worker_id)
            return

        # Log in as this current user if not already logged in
        if self.user_id is None or self.access_token is None or \
            len(self.user_id) < 1 or len(self.access_token) < 1:
            
            self.login(start_syncing = False, log_request=True)

        # The login() method sets user_id and access_token
        if self.user_id is None or self.access_token is None:
            logging.error("Login failed for User [%s]", self.username)
            return

        def username_to_userid(uname):
            uid = uname + ":" + self.matrix_domain
            if not uid.startswith("@"):
                uid = "@" + uid
            return uid

        my_rooms_info = MatrixRoomCreatorUser.worker_rooms_for_users.get(self.username, [])
        #logging.info("User [%s] Found %d rooms to be created", self.username, len(my_rooms_info))

        for room_info in my_rooms_info:
            room_name = room_info["name"]
            #room_alias = room_name.lower().replace(" ", "-")
            usernames = room_info["users"]
            user_ids = list(map(username_to_userid, usernames))
            logging.info("User [%s] Creating room [%s] with %d users",
                         self.username, room_name, len(user_ids))

            # Actually create the room
            retries = 3
            while retries > 0:
                room_id = self.create_room(alias=None, room_name=room_name, user_ids=user_ids)

                if room_id is None:
                    logging.info("[%s] Could not create room %s (attempt %d). Trying again...",
                                 self.username, room_name, 4 - retries)
                    retries -= 1
                else:
                    break

            if retries == 0:
                logging.error("[%s] Error creating room %s. Skipping...", self.username, room_name)

