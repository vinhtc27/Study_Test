################################################################################
#
# matrixuser.py - The base MatrixUser class
# -- Extend this class to write your Matrix load test
#
# Created: 2022-08-05
# Author: Charles V Wright <cvwright@futo.org>
# Copyright: 2022 FUTO Holdings Inc
# License: Apache License version 2.0
#
# The MatrixUser class provides a foundational base layer
# in Locust for other Matrix user classes can build on.
# It's sort of like a very minimal Matrix SDK for interacting
# with the homeserver through Locust.  This class aims to
# provide the functionality that would normally be part of
# the client software that a human user would use to interact
# with a Matrix server.  Child classes that inherit from this
# can then focus on mimicking the behavior of the human user.
#
################################################################################

import csv
import os
import sys
import glob
import random
import resource
import json
import logging
from http import HTTPStatus
import mimetypes

from locust import task, between, TaskSet, FastHttpUser
from locust import events
from locust.runners import MasterRunner, WorkerRunner
from collections import namedtuple

import gevent


# Locust functions for distributing users to workers ###########################

tokens_dict = {}
if os.path.exists("tokens.csv"):
  with open("tokens.csv", "r", encoding="utf-8") as csvfile:
    csv_header = ["username", "user_id", "access_token", "sync_token"]
    tokens_dict = { row["username"]: { "user_id": row["user_id"],
                                      "access_token": row["access_token"],
                                      "sync_token": row["sync_token"] }
                  for row in csv.DictReader(csvfile, fieldnames=csv_header) }
    tokens_dict.pop("username") # Dict includes the header values, so remove it

locust_users = []

################################################################################


# Preflight ####################################################################

@events.init.add_listener
def on_locust_init(environment, **_kwargs):
    # Increase resource limits to prevent OS running out of descriptors
    resource.setrlimit(resource.RLIMIT_NOFILE, (999999, 999999))

    # Register event hooks
    if isinstance(environment.runner, MasterRunner):
        print("Registered 'update_tokens' handler on master worker")
        environment.runner.register_message("update_tokens", update_tokens)

@events.test_stop.add_listener
def on_test_stop(environment, **_kwargs):
  global tokens_dict
  csv_header = ["username", "user_id", "access_token", "sync_token"]

  # Write changes to tokens.csv
  with open("tokens.csv", "w", encoding="utf-8") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=csv_header)
    writer.writeheader()

    for (k, v) in sorted(tokens_dict.items()):
      writer.writerow({"username": k, "user_id": v["user_id"],
                        "access_token": v["access_token"], "sync_token": v["sync_token"]})

@events.test_start.add_listener
def on_test_start(environment, **_kwargs):
  global locust_users
  if isinstance(environment.runner, MasterRunner):
    print("Loading users and sending to workers")
    with open("users.csv", "r", encoding="utf-8") as csvfile:
      user_reader = csv.DictReader(csvfile)
      locust_users = [ user for user in user_reader ]

      # Divide up users between all workers
      for (client_id, index) in environment.runner.worker_indexes.items():
        user_count = int(len(locust_users) / environment.runner.worker_index_max)
        remainder = 0 if index != environment.runner.worker_index_max - 1 \
                      else (len(locust_users) % environment.runner.worker_index_max)

        start = index * user_count
        end = start + user_count + remainder
        users = locust_users[start:end]

        print(f"Sending {len(users)} users to {client_id}")
        environment.runner.send_message("load_users", users, client_id)

################################################################################

def update_tokens(environment, msg, **_kwargs):
  """Updates the given user's access and sync tokens for writing to the csv file"""
  global tokens_dict
  username = msg.data["username"]
  user_id = msg.data["user_id"]
  access_token = msg.data["access_token"]
  sync_token = msg.data["sync_token"]

  tokens_dict[username] = { "user_id": user_id, "access_token": access_token, "sync_token": sync_token }

class MatrixUser(FastHttpUser):

  # Don't ever directly instantiate this class
  abstract = True

  # We need to keep some instance-level state objects
  #   * Matrix credentials (user id, access token, device id)
  #   * Sync token
  #   * Joined rooms (room_id only)
  #   * Invited rooms (room_id only)
  #   * Room avatar URLs
  #   * User avatar URLs
  #   * A pretend cache of images (by MXC URL) that we have already downloaded

  def wait_time(self):
    return random.expovariate(0.1)


  def __init__(self, *args, **kwargs):
    #global user_reader
    global locust_users
    super().__init__(*args, **kwargs)

    self.matrix_version = "v3"
    self.username = None
    self.password = None
    self.total_num_users = len(locust_users)

    # The login() method sets the Matrix credentials
    self.user_id = None
    self.access_token = None
    self.device_id = None
    # We also keep track of our local homeserver's domain.
    # This is useful for inviting other local users
    self.matrix_domain = None
    self.sync_timeout = 30

    self._reset_user_state()

  def _reset_user_state(self):
    """Resets the internal state of the matrix user

        A reset of the internal state is required when a single Locust user login into multiple
        matrix users (this base class is only initialized when a Locust user is spawned)
    """
    self.invited_room_ids = set([])
    self.joined_room_ids = set([])

    self.room_avatar_urls = {}
    self.user_avatar_urls = {}
    self.earliest_sync_tokens = {}
    self.room_display_names = {}
    self.user_display_names = {}
    self.media_cache = {}

    self.recent_messages = {}
    self.current_room = None

    self.sync_token = None
    self.initial_sync_token = None
    self.matrix_sync_task = None


  def register(self):
    """https://spec.matrix.org/v1.4/client-server-api/#post_matrixclientv3register
    """
    url = f"/_matrix/client/{self.matrix_version}/register"
    request_body = {
      "username": self.username,
      "password": self.password,
      "inhibit_login": False
    }
    with self.rest("POST", url, json=request_body) as response1:
      if response1.status_code == HTTPStatus.OK: #200
        logging.info("User [%s] Success!  Didn't even need UIAA!", self.username)
        self.user_id = response1.js.get("user_id", None)
        self.access_token = response1.js.get("access_token", None)
        if self.user_id is None or self.access_token is None:
          logging.error("User [%s] Failed to parse /register response!\nResponse: %s", self.username, response1.js)
          return
      elif response1.status_code == HTTPStatus.UNAUTHORIZED: #401
        # Not an error, unauthorized requests are apart of the registration-flow
        response1.success()

        flows = response1.js.get("flows", None)
        if flows is None:
          logging.error("User [%s] No UIAA flows for /register\nResponse: %s", self.username, response1.js)
          self.environment.runner.quit()
          return
        #for flow in flows:
        #  stages = flow.get("stages", [])
        #  if len(stages) > 0:
        #    logging.info("Found UIAA flow " + " ".join(stages))

        # FIXME: Currently we only support dummy auth
        # TODO: Add support for MSC 3231 registration tokens
        request_body["auth"] = {
          "type": "m.login.dummy"
        }

        session_id = response1.js.get("session", None)
        if session_id is None:
          logging.info("User [%s] No session ID provided by server for /register", self.username)
        else:
          request_body["auth"]["session"] = session_id

        with self.rest("POST", url, json=request_body) as response2:
          if response2.status_code == HTTPStatus.OK or response2.status_code == HTTPStatus.CREATED: # 200 or 201
            logging.info("User [%s] Success!", self.username)
            self.user_id = response2.js.get("user_id", None)
            self.access_token = response2.js.get("access_token", None)
            if self.user_id is None or self.access_token is None:
              logging.error("User [%s] Failed to parse /register response!\nResponse: %s", self.username,
                            response2.js)
          else:
            logging.error("User[%s] /register failed with status code %d\nResponse: %s", self.username,
                          response2.status_code, response2.js)
      else:
        logging.error("User[%s] /register failed with status code %d\nResponse: %s", self.username,
                      response1.status_code, response1.js)

  def start_syncing(self):
    if self.access_token is not None:
      # Spawn a Greenlet to act as this user's client, constantly /sync'ing with the server
      self.sync_timeout = 30
      self.matrix_sync_task = gevent.spawn(self.sync_forever)

      # Wait a bit before we take our first action
      self.wait()

  def login_from_csv(self, user_dict):
    """Log-in the user from the credentials saved in the csv file

    Args:
        user_dict (dictionary): dictionary of the users.csv file
    """
    global tokens_dict

    self.username = user_dict["username"]
    self.password = user_dict["password"]

    if tokens_dict.get(self.username) is None:
      self.user_id = None
      self.access_token = None
      self.sync_token = None
    else:
      self.user_id = tokens_dict[self.username].get("user_id")
      self.access_token = tokens_dict[self.username].get("access_token")
      self.sync_token = tokens_dict[self.username].get("sync_token")

      # Handle empty strings
      if len(self.user_id) < 1 or len(self.access_token) < 1:
        self.user_id = None
        self.access_token = None
        return

      if len(self.sync_token) < 1:
        self.sync_token = None

      self.matrix_domain = self.user_id.split(":")[-1]
    
    self._reset_user_state()

  def login(self, start_syncing=False, log_request=False):
    if self.username is None or self.password is None:
      logging.error("No username or password")
      self.environment.runner.quit()
      return

    self._reset_user_state()

    url = "/_matrix/client/%s/login" % self.matrix_version
    body = {
      "type": "m.login.password",
      "identifier": {
        "type": "m.id.user",
        "user": self.username
      },
      "password": self.password
    }

    try:
      request_args = { "method": "POST", "url": url, "json": body }

      # Due to the internernals of how requests are handled, different methods neeed to be
      # invoked to prevent logging
      if log_request:
        request = self.rest
      else:
        request = self.client.request
        request_args["catch_response"] = True

      # logging.info("User [%s]: sending /login request" % username)
      with request(**request_args) as response:
        #logging.info("User [%s]: Got login response" % username)
        response_json = response.json()
        self.access_token = response_json["access_token"]
        self.user_id = response_json["user_id"]
        self.device_id = response_json["device_id"]
        self.matrix_domain = self.user_id.split(":")[-1]

        # Refresh tokens stored in the csv file (Have to emulate locust message
        # object)
        msg = namedtuple("msg", ["data"])
        msg.data = { "username": self.username, "user_id": self.user_id,
                     "access_token": self.access_token, "sync_token": "" }
        update_tokens(None, msg)

        if start_syncing and self.access_token is not None:
          # Spawn a Greenlet to act as this user's client, constantly /sync'ing with the server
          self.sync_timeout = 30
          self.matrix_sync_task = gevent.spawn(self.sync_forever)

          # Wait a bit before we take our first action
          self.wait()

        # Raising an exception is the process to prevent logging a request according to the docs
        if not(log_request):
          raise Exception()
    except:
      pass


  def sync(self, initial_sync=False, timeout=30000):
    # For some reason all homeservers have issues with incremental sync when parameters are passed
    # via JSON request_body versus passing via URL
    if self.sync_token is None or initial_sync is True:
      sync_url = f"/_matrix/client/{self.matrix_version}/sync?timeout={timeout}"
    else:
      sync_url = f"/_matrix/client/{self.matrix_version}/sync?timeout={timeout}&since={self.sync_token}"

    label = f"/_matrix/client/{self.matrix_version}/sync"

    # request_body = {
    #   "since": self.sync_token,
    #   "timeout": 30000,  # Convert from seconds to milliseconds
    # }

    #logging.info("User [%s] calling /sync" % self.username)
    #with self._matrix_api_call("GET", sync_url, body=request_body, name=label) as response:
    with self._matrix_api_call("GET", sync_url, body=None, name=label) as response:
      if response.status_code != 200:
        return response

      response_json = response.json()
      if response_json is None:
        return None

      self.sync_token = response_json.get("next_batch", self.sync_token)
      if self.sync_token is None:
        logging.error("User [%s] /sync didn't get a next batch", self.username)
        #logging.error(json.dumps(response_json))
        #self.environment.runner.quit()    # Clearly this does nothing...
        return response

      if self.initial_sync_token is None:
        self.initial_sync_token = self.sync_token

      # Get any new invitations and add them to the local instance
      new_invited_room_ids = set(response_json.get("rooms", {}).get("invite", {}).keys())
      #logging.info("User [%s] /sync found %d new invited rooms", self.username, len(new_invited_room_ids))

      new_invited_room_ids.discard(None) # Remove null room id retrieved from the sync response
      self.invited_room_ids.update( new_invited_room_ids )

      # Get any new messages and add them to the local instance
      rooms = response_json.get("rooms",{}).get("join", {}) # dict: str -> JoinedRoom
      #logging.info("User [%s] /sync found %d joined rooms" % (self.username, len(rooms.keys())))
      for room_id, room in rooms.items():
        self.joined_room_ids.add(room_id)
        #timeline = room["timeline"]
        events = room.get("timeline", {}).get("events", [])
        #logging.info("User [%s] /sync found %d events in room %s" % (self.username, len(events), room_id))

        # Take only the Matrix events that are "normal" room chat messages, not state updates or whatever else
        new_messages = [e for e in events if e.get("type", None) in ["m.room.message", "m.room.encrypted"]]

        # Add the new messages to whatever we had before (if anything)
        room_messages = self.recent_messages.get(room_id, []) + new_messages
        # Store only the most recent 10 messages, regardless of how many we had before or how many we just received
        self.recent_messages[room_id] = room_messages[-10:]

        # If this is the room that the user is currently looking at,
        # then we should also load all the relevant data for display,
        # including display names, images, ...
        if room_id == self.current_room:
          self.load_data_for_room(room_id)

      # Finally, return the response to the caller
      return response



  def sync_forever(self):
    # Continually call the /sync endpoint
    # Put anything that the user might care about into our instance variables where the user @task's can find it

    while True:
      response = self.sync()

      if response is None or response.status_code == 0:
        logging.error("User [%s] /sync returned a NULL response" % self.username)

      elif response.status_code == 429:
        logging.warning("User [%s] /sync says to slow down" % self.username)
        # FIXME Handle 429 "slow down" response
        # FIXME Kludge: For now we just insert another sleep, in addition to the one at the end of the loop below :-P
        gevent.sleep(self.sync_timeout)

      elif response.status_code != 200:
        logging.error("User [%s] /sync failed with status %d: %s" % (self.username, response.status_code, response.text))
        response_json = response.json()
        if response_json is not None:
          matrix_error = response_json.get("error", "Unknown")
          matrix_errcode = response_json.get("errcode", "???")
          logging.error("User [%s] /sync error was %s: %s" % (self.username, matrix_errcode, matrix_error))



  def set_displayname(self, displayname=None):
    if self.user_id is None:
      logging.error("User [%s] Can't set displayname without a user id" % self.username)
      return

    if displayname is None:
      user_number = self.username.split(".")[-1]
      displayname = "User %s" % user_number
    #logging.info("Setting displayname for user \"%s\"" % user_number)
    url = "/_matrix/client/%s/profile/%s/displayname" % (self.matrix_version, self.user_id)
    label = "/_matrix/client/%s/profile/_/displayname" % self.matrix_version
    body = {
      "displayname": displayname
    }
    with self._matrix_api_call("PUT", url, body=body, name=label) as response:
      if "error" in response.js:
        logging.error("User [%s] failed to set displayname" % self.username)


  def set_avatar_image(self, filename):
    if self.user_id is None:
      logging.error("User [%s] Can't set avatar image without a user id" % self.username)
      return

    # Guess the mimetype of the file
    (mime_type, encoding) = mimetypes.guess_type(filename)
    # Read the contents of the file
    data = open(filename, 'rb').read()
    # Upload the file to Matrix
    mxc_url = self.upload_matrix_media(data, mime_type)
    if mxc_url is None:
      logging.error("User [%s] Failed to set avatar image" % self.username)
      return
    url = "/_matrix/client/%s/profile/%s/avatar_url" % (self.matrix_version, self.user_id)
    body = {
      "avatar_url": mxc_url
    }
    label = "/_matrix/client/%s/profile/_/avatar_url" % self.matrix_version
    response = self._matrix_api_call("POST", url, body=body, name=label)
    return response


  def create_room(self, alias, room_name, user_ids=[]):
    url = "/_matrix/client/%s/createRoom" % self.matrix_version
    request_body = {
      "preset": "private_chat",
      "name": room_name,
      "invite": user_ids
    }

    if not (alias is None):
      request_body["room_alias_name"] = alias

    #logging.info("Body is %s" % json.dumps(request_body))
    with self._matrix_api_call("POST", url, body=request_body) as response:
      #logging.info("User [%s] Back from /createRoom" % self.username)
      room_id = response.js.get("room_id", None)
      if room_id is None:
        #logging.error("User [%s] Failed to create room for [%s]" % (self.username, room_name if room_name is not None else "Unnamed room"))
        logging.error("User [%s] Failed to create room for [%s]" % (self.username, room_name))
        logging.error("%s: %s" % (response.js["errcode"], response.js["error"]))
        return None
      else:
        logging.info("User [%s] Created room [%s]" % (self.username, room_id))
        return room_id
    ## Not sure how we might end up here, but just to be safe...
    #return None


  # Child classes should implement this
  #def on_start(self):
  #  pass


  def send_matrix_event(self, room_id, event):
    txn_id = "%04x" % random.randint(0, 1<<16)

    url = "/_matrix/client/" + self.matrix_version + "/rooms/" + room_id + "/send/" + event["type"] + "/" + txn_id
    label = "/_matrix/client/" + self.matrix_version + "/rooms/_/send/" + event["type"]

    return self._matrix_api_call("PUT", url, body=event["content"], name=label)


  def logout(self):
    logging.info("User [%s] logging out" % self.username)
    if self.matrix_sync_task is not None:
      self.matrix_sync_task.kill()
    if self.access_token is not None:
      with self._matrix_api_call("POST", "/_matrix/client/%s/logout" % self.matrix_version) as _response:
        pass
    self.access_token = None
    self.user_id = None
    self.device_id = None
    self.matrix_domain = None



  def _matrix_api_call(self, method, url, body=None, name=None):
    if self.access_token is None:
      logging.warning("User [%s] API call to %s failed -- No access token" % (self.username, url))
      return

    headers = {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "Authorization": "Bearer %s" % self.access_token,
    }
    #logging.info("User [%s] Making API call to %s" % (self.username, url))
    return self.rest(method, url, headers=headers, json=body, name=name)



  def upload_matrix_media(self, data, content_type):
    url = "/_matrix/media/%s/upload" % self.matrix_version
    headers = {
      "Content-Type": content_type,
      "Accept": "application/json",
      "Authorization": "Bearer %s" % self.access_token,
    }
    response = self.client.post(url, headers=headers, data=data)
    if response.status_code == 200:
      return response.js.get("content_uri", None)
    else:
      logging.error("User [%s] Failed to upload media (HTTP %d)" % (self.username, response.status_code))
      return None


  def download_matrix_media(self, mxc):
    # Convert the MXC URL to a "real" URL
    toks = mxc.split("/")
    if len(toks) <= 2:
      logging.error("Couldn't parse MXC URL [%s]" % mxc)
    media_id = toks[-1]
    server_name = toks[-2]
    real_url = "/_matrix/media/%s/download/%s/%s" % (self.matrix_version, server_name, media_id)
    # Check in our fake "cache" -- Did we download this one already???
    cached = self.media_cache.get(mxc, False)
    if not cached:
      # Hit the Matrix /media API to download it
      label = "/_matrix/media/%s/download" % self.matrix_version
      with self._matrix_api_call("GET", real_url, name=label) as _response:
        pass
      # Mark it as cached so we don't download it again
      self.media_cache[mxc] = True



  def get_user_avatar_url(self, user_id):
    url = "/_matrix/client/%s/profile/%s/avatar_url" % (self.matrix_version, user_id)
    label = "/_matrix/client/%s/profile/_/avatar_url" % self.matrix_version
    with self._matrix_api_call("GET", url, name=label) as response:
      avatar_url = response.js.get("avatar_url", None)
      self.user_avatar_urls[user_id] = avatar_url
      #return avatar_url



  def get_user_displayname(self, user_id):
    url = "/_matrix/client/%s/profile/%s/displayname" % (self.matrix_version, user_id)
    label = "/_matrix/client/%s/profile/_/displayname" % self.matrix_version
    with self._matrix_api_call("GET", url, name=label) as response:
      displayname = response.js.get("displayname", None)
      self.user_display_names[user_id] = displayname
      return displayname



  def load_data_for_room(self, room_id):
    # FIXME Need to parse the room state for all of this :-\
    ## FIXME Load the room displayname and avatar url
    ## FIXME If we don't have it, load the avatar image
    #room_displayname = self.room_display_names.get(room_id, None)
    #if room_displayname is None:
    #  # Uh-oh, do we need to parse the room state from /sync in order to get this???
    #  pass
    #room_avatar_url = self.room_avatar_urls.get(room_id, None)
    #if room_avatar_url is None:
    #  # Uh-oh, do we need to parse the room state from /sync in order to get this???
    #  pass
    ## Note: We may have just set room_avatar_url in the code above
    #if room_avatar_url is not None and self.media_cache.get(room_avatar_url, False) is False:
    #  # FIXME Download the image and set the cache to True
    #  pass

    # Load the avatars for recent users
    # Load the thumbnails for any messages that have one
    messages = self.recent_messages.get(room_id, [])

    for message in messages:
      sender_userid = message["sender"]
      sender_avatar_mxc = self.user_avatar_urls.get(sender_userid, None)
      if sender_avatar_mxc is None:
        # FIXME Fetch the avatar URL for sender_userid
        # FIXME Set avatar_mxc
        # FIXME Set self.user_avatar_urls[sender_userid]
        self.get_user_avatar_url(sender_userid)
      # Try again.  Maybe we were able to populate the cache in the line above.
      sender_avatar_mxc = self.user_avatar_urls.get(sender_userid, None)
      # Now avatar_mxc might not be None, even if it was above
      if sender_avatar_mxc is not None and len(sender_avatar_mxc) > 0:
        self.download_matrix_media(sender_avatar_mxc)
      sender_displayname = self.user_display_names.get(sender_userid, None)
      if sender_displayname is None:
        sender_displayname = self.get_user_displayname(sender_userid)

    for message in messages:
      content = message["content"]
      msgtype = content["msgtype"]
      if msgtype in ["m.image", "m.video", "m.file"]:
        thumb_mxc = message["content"].get("thumbnail_url", None)
        if thumb_mxc is not None:
          self.download_matrix_media(thumb_mxc)

  def get_random_roomid(self):
    if len(self.joined_room_ids) > 0:
      room_id = random.choice(list(self.joined_room_ids))
      return room_id
    else:
      return None


  def join_room(self, room_id):
    if room_id in self.joined_room_ids:
      # Looks like we already joined.  Peace out.
      return
    logging.info("User [%s] joining room %s" % (self.username, room_id))
    #url = "/_matrix/client/%s/join/%s" % (self.matrix_version, room_id)    # This is the roomIdOrAlias version
    url = "/_matrix/client/%s/rooms/%s/join" % (self.matrix_version, room_id) # This is the regular /room/_/join version, which we probably should have been using all along...
    label = "/_matrix/client/%s/rooms/_/join" % self.matrix_version
    with self._matrix_api_call("POST", url, name=label) as response:
      if response.js is None:
        logging.error("User [%s] Failed to join room %s - timeout", self.username, room_id)
        response.failure("Failed to join room (timeout)")
        return None

      if "room_id" in response.js:
        logging.info("User [%s] Joined room %s" % (self.username, room_id))
        self.joined_room_ids.add(room_id)
        self.invited_room_ids.remove(room_id)
        self.load_data_for_room(room_id)
        return response.js["room_id"]
      else:
        logging.warning("User [%s] Failed to join room %s - %s: %s" % (self.username, room_id, response.js["errcode"] or "???", response.js["error"] or "Unknown"))
        response.failure("Failed to join room")
        return None

  def set_typing(self, room_id, typing):
    url = "/_matrix/client/%s/rooms/%s/typing/%s" % (self.matrix_version, room_id, self.user_id)
    body = {
      "timeout": 10 * 1000,  # Copied from Element iOS's default initial setting -- We don't do the fancy stuff that they do, trying to figure out how long since we last set this
      "typing": typing
    }
    label = "/_matrix/client/%s/rooms/_/typing/_" % self.matrix_version
    with self._matrix_api_call("PUT", url, body=body, name=label) as _response:
      pass

  def send_read_receipt(self, room_id, event_id):
    # POST /_matrix/client/v3/rooms/{roomId}/receipt/{receiptType}/{eventId}
    url = "/_matrix/client/%s/rooms/%s/receipt/m.read/%s" % (self.matrix_version, room_id, event_id)
    body = {
      "thread_id": "main"
    }
    label = "/_matrix/client/%s/rooms/_/receipt/m.read/_" % self.matrix_version
    with self._matrix_api_call("POST", url, body=body, name=label) as _response:
      pass
